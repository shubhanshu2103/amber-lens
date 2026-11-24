from pathlib import Path

from amber_lens.perception.dataset import parse_label_rows
from amber_lens.perception.evaluate import key_located, render, rule_cost, score_photo
from amber_lens.perception.fields import NAMEPLATE_FIELDS
from amber_lens.perception.reader import NameplateRun
from amber_lens.perception.scoring import Outcome
from amber_lens.schemas import BBox, PerceptionResult, ReadField, ReadStatus, SourceRef

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "perception" / "labels_sample.csv"
LABELS = {row.photo_id: row for row in parse_label_rows(FIXTURE.read_text(encoding="utf-8"))}
SOURCE = SourceRef(kind="photo_crop", ref_id="fx_01.jpg", bbox=BBox(x=0, y=0, w=10, h=10))


def _run(read: dict[str, str], rules: dict[str, str] | None = None, vision: dict[str, str] | None = None,
         path: str = "rapidocr") -> NameplateRun:
    rules = rules or {}
    vision = vision or {}
    fields = []
    for name in NAMEPLATE_FIELDS:
        if name in read:
            fields.append(ReadField(name=name, value=read[name], vision_value=read[name], status=ReadStatus.READ,
                                    source=SOURCE))
        else:
            fields.append(ReadField(name=name, value=None, vision_value=vision.get(name),
                                    status=ReadStatus.DISPUTED if name in rules else ReadStatus.UNREADABLE))
    result = PerceptionResult(observation_id="fx", fields=fields, tag_read_ok=False, model_name="m", latency_ms=1000,
                              cost_usd=0.0)
    return NameplateRun(
        result=result,
        reasons={n: (None if n in read else ("readers_disagree" if n in rules else "model_missing"))
                 for n in NAMEPLATE_FIELDS},
        rules={n: rules.get(n) for n in NAMEPLATE_FIELDS},
        located_by={n: (path if n in read else None) for n in NAMEPLATE_FIELDS},
        warnings=dict.fromkeys(NAMEPLATE_FIELDS),
    )


def test_identifier_matches_through_catalog_number() -> None:
    scores = score_photo("fx_01", _run({"model_number": "OTHER-1", "catalog_number": "FX-100A"}), LABELS["fx_01"])
    model = next(s for s in scores if s.field == "model_number")
    assert model.outcome is Outcome.CORRECT and model.matched_via == "catalog_number"
    assert model.located_by == "rapidocr"


def test_wrong_and_extra_reads_are_counted() -> None:
    scores = {s.field: s for s in score_photo("fx_01", _run({"voltage": "400 V"}), LABELS["fx_01"])}
    assert scores["voltage"].outcome is Outcome.WRONG
    assert scores["rated_current"].outcome is Outcome.MISSED
    extra = {s.field: s for s in score_photo("fx_02", _run({"model_number": "GUESS-1"}), LABELS["fx_02"])}
    assert extra["model_number"].outcome is Outcome.EXTRA


def test_key_located_counts_each_identifier_once() -> None:
    runs = {"fx_01": _run({"model_number": "FX-100A", "catalog_number": "FX-100A", "voltage": "230/460 V"})}
    assert key_located(runs, LABELS) == (2, 3)


def test_rule_cost_counts_correct_values_held_back() -> None:
    runs = {
        "fx_01": _run({}, rules={"frequency": "multi_rating", "voltage": "multi_rating"},
                      vision={"frequency": "60 Hz", "voltage": "400 V"}),
    }
    cost = rule_cost(runs, LABELS, "multi_rating")
    assert cost["frequency"] == (1, 1)
    assert cost["voltage"] == (1, 0)
    assert cost["rated_current"] == (0, 0)


def test_render_lists_wrong_reads_with_their_path() -> None:
    runs = {"fx_01": _run({"voltage": "400 V"}, path="full_ocr")}
    scores = score_photo("fx_01", runs["fx_01"], LABELS["fx_01"])
    text = render(scores, runs, LABELS)
    assert "- fx_01 voltage: read '400 V', label '230/460 V', via full_ocr" in text
    assert "key values located: 1 of 3 labelled (33%)" in text
