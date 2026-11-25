from pathlib import Path

import pytest

from amber_lens.perception.dataset import (
    DatasetError,
    ensure_not_heldout,
    load_tuning_labels,
    parse_label_rows,
    tuning_photo_path,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "perception" / "labels_sample.csv"


def _data_dir(tmp_path: Path) -> Path:
    (tmp_path / "labels.csv").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_parse_maps_columns_to_field_names() -> None:
    rows = parse_label_rows(FIXTURE.read_text(encoding="utf-8"))
    first = rows[0]
    assert first.truth == {
        "model_number": "FX-100A",
        "voltage": "230/460 V",
        "rated_current": "4.2/2.1 A",
        "power": "2 HP",
        "frequency": "60 Hz",
        "manufacturer": "Example Motors",
    }
    assert first.readable is True


def test_unprinted_values_become_none() -> None:
    second = parse_label_rows(FIXTURE.read_text(encoding="utf-8"))[1]
    assert second.readable is False
    assert set(second.truth.values()) == {None}


def test_missing_columns_raise() -> None:
    with pytest.raises(DatasetError, match="missing columns"):
        parse_label_rows("photo_id,file_name\nx,x.jpg\n")


def test_load_tuning_labels_drops_heldout_rows(tmp_path: Path) -> None:
    labels = load_tuning_labels(_data_dir(tmp_path))
    assert set(labels) == {"fx_01", "fx_02"}


def test_load_tuning_labels_needs_the_file(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="AMBER_DATA_DIR"):
        load_tuning_labels(tmp_path)


def test_heldout_paths_are_refused() -> None:
    with pytest.raises(DatasetError, match="held-out"):
        ensure_not_heldout(Path("data/photos/heldout/x.jpg"))
    ensure_not_heldout(Path("data/photos/tuning/x.jpg"))


def test_tuning_photo_path(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    row = load_tuning_labels(data_dir)["fx_01"]
    with pytest.raises(DatasetError, match="not found"):
        tuning_photo_path(data_dir, row)
    photo = data_dir / "photos" / "tuning" / "fx_01.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"jpg")
    assert tuning_photo_path(data_dir, row) == photo


def test_tuning_photo_path_refuses_other_splits(tmp_path: Path) -> None:
    heldout_row = parse_label_rows(FIXTURE.read_text(encoding="utf-8"))[2]
    with pytest.raises(DatasetError, match="not tuning"):
        tuning_photo_path(tmp_path, heldout_row)
