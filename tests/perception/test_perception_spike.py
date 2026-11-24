from pathlib import Path

import pytest

from amber_lens.perception import spike
from amber_lens.perception.dataset import parse_label_rows
from amber_lens.perception.ocr import OcrLine, OcrWord
from amber_lens.perception.scoring import Outcome
from amber_lens.perception.spike import (
    ArmReading,
    apply_format_rules,
    disagreements,
    keep_located,
    latency_summary,
    render_markdown,
    score_arm,
)
from amber_lens.schemas import BBox

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "perception" / "labels_sample.csv"
LABELS = {row.photo_id: row for row in parse_label_rows(FIXTURE.read_text(encoding="utf-8"))}


def _values(**kwargs) -> dict:
    base = dict.fromkeys(("model_number", "voltage", "rated_current", "power", "frequency", "manufacturer"))
    base.update(kwargs)
    return base


READINGS = [
    ArmReading("a", "fx_01", _values(model_number="FX-100A", voltage="230/460 V", rated_current="9 A"), 1000),
    ArmReading("a", "fx_02", _values(model_number="GUESS-1"), 3000),
]


def test_rules_drop_failing_values_without_repair() -> None:
    kept = apply_format_rules(_values(model_number="FX-100A", voltage="231 V", power="3"))
    assert kept["model_number"] == "FX-100A"
    assert kept["voltage"] is None
    assert kept["power"] is None


def test_keep_located_drops_values_not_printed() -> None:
    words = tuple(
        OcrWord(text=t, conf=90.0, bbox=BBox(x=10 * i, y=0, w=8, h=8), line_key=(1, 1, 1))
        for i, t in enumerate(["MODEL", "FX-100A", "VOLTS", "230/460"])
    )
    lines = (OcrLine(text="MODEL FX-100A VOLTS 230/460", bbox=BBox(x=0, y=0, w=40, h=8), words=words),)
    kept = keep_located(_values(model_number="FX-100A", voltage="400 V", power=None), lines)
    assert kept["model_number"] == "FX-100A"
    assert kept["voltage"] is None
    assert kept["power"] is None


def test_score_arm_counts() -> None:
    scores = score_arm(READINGS, LABELS, ("model_number", "rated_current"))
    assert scores["model_number"][Outcome.CORRECT] == 1
    assert scores["model_number"][Outcome.EXTRA] == 1
    assert scores["rated_current"][Outcome.WRONG] == 1
    assert scores["rated_current"][Outcome.ABSTAINED_OK] == 1


def test_disagreements_list_wrong_and_extra() -> None:
    rows = disagreements(READINGS, LABELS, ("model_number", "rated_current"))
    assert {(r["photo_id"], r["field"], r["outcome"]) for r in rows} == {
        ("fx_01", "rated_current", "wrong"),
        ("fx_02", "model_number", "extra"),
    }


def test_latency_summary() -> None:
    assert latency_summary([1000, 3000]) == {"mean_s": 2.0, "median_s": 2.0, "max_s": 3.0}
    with pytest.raises(ValueError):
        latency_summary([])


def test_render_markdown_has_one_row_per_arm() -> None:
    text = render_markdown(READINGS, LABELS, ["a"])
    assert "| a | 2 | 1 | 1 | 0 | 2 | 2 | 2.0 / 2.0 / 3.0 |" in text
    assert "| a | fx_02 | model_number | None | GUESS-1 |" in text


def test_main_stops_when_spike_photos_are_not_tuning_rows(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "labels.csv").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("AMBER_DATA_DIR", str(tmp_path))
    assert spike.main([]) == 2
    assert "not in the tuning labels" in capsys.readouterr().err
