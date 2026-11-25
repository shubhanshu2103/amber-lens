from pathlib import Path

import pytest

from amber_lens.perception.cache import ResponseCache, image_sha256

DIGEST = image_sha256(b"photo bytes")


def test_round_trip(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    assert cache.get(DIGEST, "m:1", "v1") is None
    path = cache.put(DIGEST, "m:1", "v1", {"raw_text": "{}", "latency_ms": 5})
    assert path.is_file()
    assert cache.get(DIGEST, "m:1", "v1") == {"raw_text": "{}", "latency_ms": 5}


def test_keys_separate_model_and_prompt_version(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put(DIGEST, "m:1", "v1", {"raw_text": "a"})
    assert cache.get(DIGEST, "m:2", "v1") is None
    assert cache.get(DIGEST, "m:1", "v2") is None


def test_model_name_is_made_path_safe(tmp_path: Path) -> None:
    path = ResponseCache(tmp_path).path_for(DIGEST, "qwen2.5vl:3b", "nameplate-v2")
    assert path.parent.parent.name == "qwen2.5vl_3b"


def test_corrupt_entry_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    path = cache.put(DIGEST, "m", "v1", {"raw_text": "a"})
    path.write_text("{not json", encoding="utf-8")
    assert cache.get(DIGEST, "m", "v1") is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert cache.get(DIGEST, "m", "v1") is None


def test_bad_digest_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sha256"):
        ResponseCache(tmp_path).path_for("../../etc", "m", "v1")
