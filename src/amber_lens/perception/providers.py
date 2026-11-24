"""Pick the configured vision provider: local Ollama (default) or Groq."""

from __future__ import annotations

from amber_lens.perception.cache import ResponseCache
from amber_lens.perception.config import Settings
from amber_lens.perception.vision import OllamaVision, VisionError


def default_vision(settings: Settings):
    """The vision client named by VISION_PROVIDER, sharing the on-disk response cache."""
    cache = ResponseCache(settings.cache_dir / "vision")
    if settings.vision_provider == "groq":
        from amber_lens.perception.groq import GroqVision

        return GroqVision(settings.groq_api_key, settings.groq_model, cache)
    if settings.vision_provider != "ollama":
        raise VisionError(f"unknown VISION_PROVIDER {settings.vision_provider!r}; use ollama or groq")
    return OllamaVision(settings.ollama_host, settings.vision_model, cache)
