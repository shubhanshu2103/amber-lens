"""Runtime settings for perception, read from the process environment and .env."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "../amber-lens-data/data"
DEFAULT_CACHE_DIR = ".cache/perception"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
# Chosen in the reader spike (#8); qwen2.5vl:3b is a dev setting only, never used for reported numbers.
DEFAULT_VISION_MODEL = "qwen2.5vl:7b"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cache_dir: Path
    ollama_host: str
    vision_model: str
    vision_provider: str = "ollama"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    vision_fallback: str = "none"


def _resolve(raw: str, root: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _normalise_host(raw: str) -> str:
    host = raw.strip().rstrip("/")
    return host if host.startswith(("http://", "https://")) else f"http://{host}"


def settings_from_mapping(env: Mapping[str, str], root: Path = REPO_ROOT) -> Settings:
    """Build settings from a plain mapping; relative paths resolve against the repo root."""
    model = (env.get("VISION_MODEL_NAME") or "").strip() or DEFAULT_VISION_MODEL
    return Settings(
        data_dir=_resolve(env.get("AMBER_DATA_DIR") or DEFAULT_DATA_DIR, root),
        cache_dir=_resolve(env.get("AMBER_CACHE_DIR") or DEFAULT_CACHE_DIR, root),
        ollama_host=_normalise_host(env.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST),
        vision_model=model,
        vision_provider=(env.get("VISION_PROVIDER") or "ollama").strip().lower(),
        groq_api_key=(env.get("GROQ_API_KEY") or "").strip(),
        groq_model=(env.get("GROQ_MODEL") or "qwen/qwen3.8-27b").strip(),
        vision_fallback=(env.get("VISION_FALLBACK") or "none").strip().lower(),
    )


def load_settings(root: Path = REPO_ROOT) -> Settings:
    """Process environment wins over .env, which wins over defaults."""
    file_values = {k: v for k, v in dotenv_values(root / ".env").items() if v is not None}
    return settings_from_mapping({**file_values, **os.environ}, root)
