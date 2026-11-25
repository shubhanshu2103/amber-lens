"""On-disk cache of model responses, keyed by image hash, model name and prompt version."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def image_sha256(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _safe(name: str) -> str:
    return _UNSAFE.sub("_", name)


class ResponseCache:
    """JSON files under root/<model>/<prompt_version>/<image_sha256>.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, image_hash: str, model: str, prompt_version: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", image_hash):
            raise ValueError(f"not a sha256 hex digest: {image_hash!r}")
        return self.root / _safe(model) / _safe(prompt_version) / f"{image_hash}.json"

    def get(self, image_hash: str, model: str, prompt_version: str) -> dict | None:
        """Cached entry, or None on a miss. An unreadable entry counts as a miss and is rewritten on put."""
        path = self.path_for(image_hash, model, prompt_version)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        return entry if isinstance(entry, dict) else None

    def put(self, image_hash: str, model: str, prompt_version: str, entry: dict) -> Path:
        path = self.path_for(image_hash, model, prompt_version)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        # Atomic replace so a crash never leaves a half-written entry.
        os.replace(tmp, path)
        return path
