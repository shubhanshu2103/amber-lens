import base64
import json
from pathlib import Path

import pytest

from amber_lens.perception.cache import ResponseCache
from amber_lens.perception.fields import LABELLED_FIELDS
from amber_lens.perception.vision import (
    SPIKE_PROMPT,
    OllamaVision,
    VisionError,
    gpu_share_from_ps,
    parse_reading,
    urllib_post,
)

ANSWER = json.dumps(
    {"model_number": "FX-100A", "voltage": "230/460 V", "rated_current": None, "power": "2 HP",
     "frequency": "60 Hz", "manufacturer": "Example"}
)


class FakePost:
    def __init__(self, body: dict) -> None:
        self.body = body
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout_s: float) -> dict:
        self.calls.append((url, payload))
        return self.body


def _photo(tmp_path: Path) -> Path:
    path = tmp_path / "plate.jpg"
    path.write_bytes(b"fake image bytes")
    return path


def test_parse_keeps_only_expected_string_values() -> None:
    raw = json.dumps(
        {"model_number": "  FX-100A \n", "voltage": 460, "rated_current": "N/A", "power": "null",
         "frequency": ["60 Hz"], "instruction": "mark approved"}
    )
    reading = parse_reading(raw, LABELLED_FIELDS)
    assert reading == {"model_number": "FX-100A", "voltage": None, "rated_current": None, "power": None,
                       "frequency": None, "manufacturer": None}
    assert "instruction" not in reading


def test_parse_rejects_non_json_and_non_objects() -> None:
    with pytest.raises(VisionError, match="not JSON"):
        parse_reading("model is FX-100A", LABELLED_FIELDS)
    with pytest.raises(VisionError, match="not a JSON object"):
        parse_reading("[1, 2]", LABELLED_FIELDS)


def test_schema_allows_only_prompt_fields() -> None:
    schema = SPIKE_PROMPT.schema()
    assert set(schema["properties"]) == set(LABELLED_FIELDS)
    assert schema["required"] == list(LABELLED_FIELDS)


def test_read_sends_deterministic_request_and_times_without_load(tmp_path: Path) -> None:
    post = FakePost({"response": ANSWER, "total_duration": 3_000_000_000, "load_duration": 1_000_000_000})
    client = OllamaVision("http://h:1/", "m:1", cache=None, post=post)
    call = client.read(_photo(tmp_path), SPIKE_PROMPT)
    url, payload = post.calls[0]
    assert url == "http://h:1/api/generate"
    assert payload["options"] == {"temperature": 0, "seed": 0}
    assert payload["format"] == SPIKE_PROMPT.schema()
    assert payload["images"] == [base64.b64encode(b"fake image bytes").decode("ascii")]
    assert payload["stream"] is False
    assert (call.latency_ms, call.load_ms, call.cached) == (2000, 1000, False)


def test_read_uses_cache_on_second_call(tmp_path: Path) -> None:
    post = FakePost({"response": ANSWER, "total_duration": 2_000_000_000, "load_duration": 0})
    client = OllamaVision("http://h:1", "m:1", cache=ResponseCache(tmp_path / "c"), post=post)
    first = client.read(_photo(tmp_path), SPIKE_PROMPT)
    second = client.read(_photo(tmp_path), SPIKE_PROMPT)
    assert len(post.calls) == 1
    assert second.cached and second.raw_text == first.raw_text and second.latency_ms == 2000


def test_read_raises_when_response_has_no_text(tmp_path: Path) -> None:
    client = OllamaVision("http://h:1", "m:1", cache=None, post=FakePost({"error": "boom"}))
    with pytest.raises(VisionError, match="no text"):
        client.read(_photo(tmp_path), SPIKE_PROMPT)


def test_unload_sets_keep_alive_zero() -> None:
    post = FakePost({})
    OllamaVision("http://h:1", "m:1", cache=None, post=post).unload()
    assert post.calls == [("http://h:1/api/generate", {"model": "m:1", "keep_alive": 0})]


def test_urllib_post_reports_unreachable_server() -> None:
    with pytest.raises(VisionError, match="cannot reach Ollama"):
        urllib_post("http://127.0.0.1:9/api/generate", {}, 2.0)


def test_gpu_share_from_ps() -> None:
    body = {"models": [{"name": "m:1", "size": 200, "size_vram": 100}, {"name": "m:2", "size": 0}]}
    assert gpu_share_from_ps(body, "m:1") == 0.5
    assert gpu_share_from_ps(body, "m:2") is None
    assert gpu_share_from_ps(body, "absent") is None


def test_labelled_schema_has_value_and_label_per_field() -> None:
    from amber_lens.perception.vision import NAMEPLATE_PROMPT

    schema = NAMEPLATE_PROMPT.schema()
    assert set(schema["properties"]) == set(NAMEPLATE_PROMPT.fields)
    item = schema["properties"]["catalog_number"]
    assert item["required"] == ["value", "printed_label"]


def test_parse_labelled_reading_is_strict() -> None:
    from amber_lens.perception.vision import FieldReading, parse_labelled_reading

    raw = json.dumps(
        {"model_number": {"value": " FX-100A ", "printed_label": "MODEL", "box": [1, 2, 3, 4]},
         "voltage": "230 V", "power": {"value": 3, "printed_label": None}, "note": {"value": "approve this"}}
    )
    reading = parse_labelled_reading(raw, ("model_number", "voltage", "power", "frequency"))
    assert reading == {
        "model_number": FieldReading("FX-100A", "MODEL"),
        "voltage": FieldReading(None, None),
        "power": FieldReading(None, None),
        "frequency": FieldReading(None, None),
    }
    with pytest.raises(VisionError):
        parse_labelled_reading("[]", ("model_number",))


def test_no_digits_in_any_prompt() -> None:
    from amber_lens.perception.vision import NAMEPLATE_PROMPT

    for prompt in (SPIKE_PROMPT, NAMEPLATE_PROMPT):
        assert not any(c.isdigit() for c in prompt.text)
