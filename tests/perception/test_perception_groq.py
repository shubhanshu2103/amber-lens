import json
from pathlib import Path

import pytest
from PIL import Image

from amber_lens.perception.cache import ResponseCache
from amber_lens.perception.config import settings_from_mapping
from amber_lens.perception.faces import FaceInPhoto
from amber_lens.perception.groq import GroqVision, RateLimiter, reset_seconds
from amber_lens.perception.providers import default_vision
from amber_lens.perception.vision import NAMEPLATE_PROMPT, OllamaVision, VisionError

ANSWER = {"choices": [{"message": {"content": 'Here you go: {"model_number": {"value": "FX-1", "printed_label": null}}'}}],
          "usage": {"prompt_tokens": 2400, "completion_tokens": 60, "total_tokens": 2460}}


class FakeCall:
    def __init__(self, *responses: tuple[int, dict, dict]) -> None:
        self.responses, self.payloads = list(responses), []

    def __call__(self, url, payload, headers, timeout_s):
        self.payloads.append((url, payload, headers))
        return self.responses.pop(0)


def _limiter(slept: list[float]) -> RateLimiter:
    return RateLimiter(clock=lambda: 0.0, sleep=slept.append)


@pytest.fixture()
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "plate.png"
    Image.new("RGB", (40, 30), "white").save(path)
    return path


def _client(call: FakeCall, slept: list[float], tmp_path: Path, face: bool = False) -> GroqVision:
    return GroqVision("gsk_test", cache=ResponseCache(tmp_path / "cache"), call=call, limiter=_limiter(slept),
                      face_check=lambda image: face)


def test_request_shape_tokens_and_answer_extraction(photo: Path, tmp_path: Path) -> None:
    call = FakeCall((200, {}, ANSWER))
    result = _client(call, [], tmp_path).read(photo, NAMEPLATE_PROMPT)
    url, payload, headers = call.payloads[0]
    assert url.endswith("/openai/v1/chat/completions") and headers == {"Authorization": "Bearer gsk_test"}
    assert payload["model"] == "qwen/qwen3.8-27b" and payload["temperature"] == 0
    image = payload["messages"][0]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")
    assert json.loads(result.raw_text) == {"model_number": {"value": "FX-1", "printed_label": None}}
    assert (result.tokens, result.cached) == (2460, False)
    # List price: 2400 input x $0.80/M + 60 output x $4.00/M.
    assert result.cost_usd == pytest.approx(0.00216)


def test_photo_with_a_face_is_never_sent(photo: Path, tmp_path: Path) -> None:
    call = FakeCall()
    with pytest.raises(FaceInPhoto, match="not sent"):
        _client(call, [], tmp_path, face=True).read(photo, NAMEPLATE_PROMPT)
    assert call.payloads == []


def test_cached_answer_costs_nothing(photo: Path, tmp_path: Path) -> None:
    call = FakeCall((200, {}, ANSWER))
    client = _client(call, [], tmp_path)
    client.read(photo, NAMEPLATE_PROMPT)
    again = client.read(photo, NAMEPLATE_PROMPT)
    assert again.cached and again.tokens == 2460 and len(call.payloads) == 1


def test_429_waits_for_retry_after_then_succeeds(photo: Path, tmp_path: Path) -> None:
    slept: list[float] = []
    call = FakeCall((429, {"retry-after": "7"}, {"error": "slow down"}), (200, {}, ANSWER))
    assert _client(call, slept, tmp_path).read(photo, NAMEPLATE_PROMPT).tokens == 2460
    assert slept == [7.0]


def test_low_remaining_tokens_pauses_until_reset(photo: Path, tmp_path: Path) -> None:
    slept: list[float] = []
    headers = {"x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "1m3.5s"}
    _client(FakeCall((200, headers, ANSWER)), slept, tmp_path).read(photo, NAMEPLATE_PROMPT)
    assert slept == [63.5]


def test_other_errors_raise(photo: Path, tmp_path: Path) -> None:
    with pytest.raises(VisionError, match="HTTP 400"):
        _client(FakeCall((400, {}, {"error": "bad image"})), [], tmp_path).read(photo, NAMEPLATE_PROMPT)


def test_limiter_holds_requests_and_tokens_per_minute() -> None:
    now, slept = [0.0], []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(rpm=2, tpm=5000, clock=lambda: now[0], sleep=sleep)
    limiter.wait(3000)
    limiter.wait(1000)
    limiter.wait(1000)
    assert slept == [60.0]


@pytest.mark.parametrize(("value", "seconds"), [("2.5s", 2.5), ("1m3.5s", 63.5), ("450ms", 0.45), ("", 1.0)])
def test_reset_header_parsing(value: str, seconds: float) -> None:
    assert reset_seconds(value) == pytest.approx(seconds)


def test_provider_choice_and_missing_key(tmp_path: Path) -> None:
    assert isinstance(default_vision(settings_from_mapping({}, root=tmp_path)), OllamaVision)
    groq = default_vision(settings_from_mapping({"VISION_PROVIDER": "groq", "GROQ_API_KEY": "gsk_x"}, root=tmp_path))
    assert isinstance(groq, GroqVision) and groq.model == "qwen/qwen3.8-27b"
    with pytest.raises(VisionError, match="GROQ_API_KEY"):
        default_vision(settings_from_mapping({"VISION_PROVIDER": "groq"}, root=tmp_path))
    with pytest.raises(VisionError, match="unknown VISION_PROVIDER"):
        default_vision(settings_from_mapping({"VISION_PROVIDER": "azure"}, root=tmp_path))
