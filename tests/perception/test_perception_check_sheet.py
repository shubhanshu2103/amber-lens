from pathlib import Path

import pytest

from amber_lens.perception.check_sheet import CheckEntry, CheckRow, build_entries, data_uri, render_check_sheet
from amber_lens.perception.dataset import DatasetError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "perception" / "labels_sample.csv"


def _data_dir(tmp_path: Path) -> Path:
    (tmp_path / "labels.csv").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    photo = tmp_path / "photos" / "tuning" / "fx_01.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"\xff\xd8 tiny")
    return tmp_path


def _results(photo_ids: list[str]) -> dict:
    return {
        "photos": photo_ids,
        "readings": [
            {"arm": "vision:m", "photo_id": "fx_01", "values": {"model_number": "FX-100A"}},
            {"arm": "vision+rule:m", "photo_id": "fx_01", "values": {"model_number": "FX-100A"}},
            {"arm": "ocr", "photo_id": "fx_01", "values": {"model_number": "FX-1OOA"}},
        ],
    }


def test_values_are_escaped() -> None:
    entry = CheckEntry("p<1>", "data:image/png;base64,AA==", (CheckRow("model_number", "<b>x</b>", {"a": "1 & 2"}),))
    page = render_check_sheet([entry], ["a"])
    assert "<b>x</b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert "1 &amp; 2" in page
    assert "p&lt;1&gt;" in page


def test_build_entries_skips_rule_arm_and_embeds_photo(tmp_path: Path) -> None:
    entries, arms = build_entries(_results(["fx_01"]), _data_dir(tmp_path))
    assert arms == ["ocr", "vision:m"]
    assert entries[0].image_uri.startswith("data:image/jpeg;base64,")
    model_row = entries[0].rows[0]
    assert model_row.label == "FX-100A"
    assert model_row.readings == {"ocr": "FX-1OOA", "vision:m": "FX-100A"}


def test_build_entries_refuses_non_tuning_photo(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="not a tuning photo"):
        build_entries(_results(["fx_03"]), _data_dir(tmp_path))


def test_build_entries_needs_the_photo(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    with pytest.raises(DatasetError, match="not found"):
        build_entries(_results(["fx_02"]), data_dir)


def test_data_uri_rejects_other_types(tmp_path: Path) -> None:
    path = tmp_path / "x.gif"
    path.write_bytes(b"GIF")
    with pytest.raises(ValueError, match="unsupported"):
        data_uri(path)
