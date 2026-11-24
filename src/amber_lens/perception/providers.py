"""Pick the configured vision provider: local Ollama (default) or Groq."""

from __future__ import annotations

from amber_lens.perception.cache import ResponseCache
from amber_lens.perception.config import Settings
from amber_lens.perception.vision import OllamaVision, VisionCall, VisionError, VisionPrompt


def default_vision(settings: Settings):
    """The vision client named by VISION_PROVIDER, sharing the on-disk response cache."""
    cache = ResponseCache(settings.cache_dir / "vision")
    if settings.vision_provider == "groq":
        from amber_lens.perception.groq import GroqVision

        return GroqVision(settings.groq_api_key, settings.groq_model, cache)
    if settings.vision_provider != "ollama":
        raise VisionError(f"unknown VISION_PROVIDER {settings.vision_provider!r}; use ollama or groq")
    return OllamaVision(settings.ollama_host, settings.vision_model, cache)


def fallback_vision(settings: Settings):
    """Local Ollama when VISION_FALLBACK=ollama, else None (the deployed server has no Ollama)."""
    if settings.vision_fallback == "ollama":
        return OllamaVision(settings.ollama_host, settings.vision_model, ResponseCache(settings.cache_dir / "vision"))
    return None


def read_with_fallback(vision, fallback, photo_path, prompt: VisionPrompt) -> tuple[VisionCall | None, str | None]:
    """The first provider that answers, or (None, why) when every provider failed. A face is not a failure."""
    errors = []
    for client in (vision, fallback):
        if client is not None:
            try:
                return client.read(photo_path, prompt), None
            except VisionError as exc:
                errors.append(f"{client.model}: {exc}")
    return None, "; ".join(errors)
