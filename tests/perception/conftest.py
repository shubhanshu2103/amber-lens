import importlib.util
import json
import urllib.request

import pytest

from amber_lens.perception.config import load_settings
from amber_lens.perception.ocr import OcrUnavailable, find_tesseract


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "local_model: needs Ollama with the vision model and both OCR engines")


def _local_model_available() -> bool:
    settings = load_settings()
    try:
        with urllib.request.urlopen(f"{settings.ollama_host}/api/tags", timeout=2) as response:
            names = {m["name"] for m in json.load(response)["models"]}
        find_tesseract()
    except (OSError, OcrUnavailable, ValueError, KeyError):
        return False
    return settings.vision_model in names and importlib.util.find_spec("rapidocr") is not None


def pytest_collection_modifyitems(config, items) -> None:
    local = [item for item in items if "local_model" in item.keywords]
    if local and not _local_model_available():
        for item in local:
            item.add_marker(pytest.mark.skip(reason="Ollama, the vision model or an OCR engine is not available"))
