"""Groq vision provider (OpenAI-compatible chat API). Photos with a face are never sent; answers are cached.

The strict READ rule does not change: local OCR still has to confirm every value the model reads.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from amber_lens.perception.cache import ResponseCache, image_sha256
from amber_lens.perception.faces import FaceInPhoto, has_face
from amber_lens.perception.vision import VisionCall, VisionError, VisionPrompt

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
# Groq rate-limits page (read 2026-11-24): 30 requests and 8K tokens per minute; 2048 input tokens per image.
REQUESTS_PER_MINUTE, TOKENS_PER_MINUTE, IMAGE_TOKENS = 30, 8000, 2048
MAX_OUTPUT_TOKENS, MAX_RETRIES = 512, 3
# Groq list price for qwen/qwen3.8-27b in USD per 1M tokens (models page, 2026-11-24); the free tier charges 0.
PRICE_INPUT, PRICE_OUTPUT = 0.80, 4.00
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

HttpCall = Callable[[str, dict, dict, float], tuple[int, dict[str, str], dict]]


def urllib_call(url: str, payload: dict, headers: dict, timeout_s: float) -> tuple[int, dict[str, str], dict]:
    """POST JSON; returns (status, lower-cased headers, body) for any HTTP status."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     # Groq's edge refuses urllib's default client name (Cloudflare 1010).
                                     headers={"Content-Type": "application/json", "User-Agent": "amber-lens/0.1",
                                              **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, json.load(response)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        body = json.loads(text) if text.startswith("{") else {"error": text[:300]}
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise VisionError(f"cannot reach Groq: {exc}") from exc


def reset_seconds(value: str) -> float:
    """Groq reset headers look like '2.5s', '1m3.5s' or '450ms'."""
    match = re.fullmatch(r"(?:(\d+)m)?(?:([\d.]+)s)?(?:([\d.]+)ms)?", value.strip())
    if not match or not value.strip():
        return 1.0
    minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return minutes * 60 + seconds + millis / 1000


class RateLimiter:
    """Sliding one-minute window over requests and estimated tokens."""

    def __init__(self, rpm: int = REQUESTS_PER_MINUTE, tpm: int = TOKENS_PER_MINUTE,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.rpm, self.tpm, self.clock, self.sleep = rpm, tpm, clock, sleep
        self.events: deque[tuple[float, int]] = deque()

    def wait(self, tokens: int) -> None:
        while True:
            now = self.clock()
            while self.events and now - self.events[0][0] >= 60:
                self.events.popleft()
            if len(self.events) < self.rpm and sum(t for _, t in self.events) + tokens <= self.tpm:
                self.events.append((now, tokens))
                return
            self.sleep(max(60 - (now - self.events[0][0]), 0.05))


def _json_object(text: str) -> str:
    """The model's answer as one JSON object; any text around it (a reasoning preamble) is dropped."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


class GroqVision:
    """One Groq model. Same contract as OllamaVision.read."""

    def __init__(self, api_key: str, model: str = DEFAULT_GROQ_MODEL, cache: ResponseCache | None = None,
                 call: HttpCall = urllib_call, limiter: RateLimiter | None = None,
                 face_check: Callable[[Image.Image], bool] = has_face, timeout_s: float = 120.0) -> None:
        if not api_key:
            raise VisionError("GROQ_API_KEY is not set; add it to .env")
        self.api_key, self.model, self.cache, self.call = api_key, model, cache, call
        self.limiter, self.face_check, self.timeout_s = limiter or RateLimiter(), face_check, timeout_s

    def read(self, image_path: Path, prompt: VisionPrompt) -> VisionCall:
        image_bytes = image_path.read_bytes()
        digest = image_sha256(image_bytes)
        entry = self.cache.get(digest, self.model, prompt.version) if self.cache is not None else None
        cached = entry is not None and isinstance(entry.get("raw_text"), str)
        if not cached:
            with Image.open(io.BytesIO(image_bytes)) as image:
                if self.face_check(image):
                    raise FaceInPhoto(f"A face was found in {image_path.name}; it was not sent to Groq.")
            entry = self._generate(image_bytes, _MIME.get(image_path.suffix.casefold(), "image/jpeg"), prompt)
            if self.cache is not None:
                self.cache.put(digest, self.model, prompt.version, entry)
        return VisionCall(self.model, prompt.version, digest, entry["raw_text"], int(entry.get("latency_ms", 0)),
                          0, cached, int(entry.get("tokens", 0)), float(entry.get("cost_usd", 0.0)))

    def _generate(self, image_bytes: bytes, mime: str, prompt: VisionPrompt) -> dict:
        image_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = {
            "model": self.model, "temperature": 0, "seed": 0, "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt.text},
                                                      {"type": "image_url", "image_url": {"url": image_url}}]}],
        }
        estimate = IMAGE_TOKENS + len(prompt.text) // 3 + MAX_OUTPUT_TOKENS
        for attempt in range(MAX_RETRIES + 1):
            self.limiter.wait(estimate)
            started = time.perf_counter()
            status, headers, body = self.call(GROQ_URL, payload, {"Authorization": f"Bearer {self.api_key}"},
                                              self.timeout_s)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if status == 429 and attempt < MAX_RETRIES:
                self.limiter.sleep(float(headers.get("retry-after", "5")))
                continue
            if status != 200:
                raise VisionError(f"Groq returned HTTP {status}: {str(body)[:200]}")
            break
        # Pause before the next call when Groq says this minute's token budget is nearly spent.
        if int(headers.get("x-ratelimit-remaining-tokens", estimate)) < estimate:
            self.limiter.sleep(reset_seconds(headers.get("x-ratelimit-reset-tokens", "1s")))
        usage = body.get("usage") or {}
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return {"raw_text": _json_object(text), "latency_ms": latency_ms, "tokens": int(usage.get("total_tokens", 0)),
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "cost_usd": (int(usage.get("prompt_tokens", 0)) * PRICE_INPUT
                             + int(usage.get("completion_tokens", 0)) * PRICE_OUTPUT) / 1e6}
