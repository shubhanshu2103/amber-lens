"""Tuning-set access: labels.csv rows and photo paths.

Only rows with split == "tuning" are ever returned, and any path under a held-out folder is refused
before it is touched.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from amber_lens.perception.fields import LABELLED_FIELDS

# labels.csv column -> perception field name.
LABEL_COLUMNS: dict[str, str] = {
    "model_number": "model_number",
    "voltage": "voltage",
    "amps": "rated_current",
    "hp_or_kw": "power",
    "frequency": "frequency",
    "manufacturer": "manufacturer",
}

# Label values that mean the plate does not print the field.
NOT_PRINTED: frozenset[str] = frozenset({"", "unbranded", "not shown"})

TUNING = "tuning"


class DatasetError(ValueError):
    """labels.csv or a photo path is missing, malformed or outside the tuning split."""


@dataclass(frozen=True)
class LabelRow:
    photo_id: str
    file_name: str
    split: str
    readable: bool
    truth: dict[str, str | None]


def _truth_value(raw: str | None) -> str | None:
    value = " ".join((raw or "").split())
    return None if value.casefold() in NOT_PRINTED else value


def parse_label_rows(csv_text: str) -> list[LabelRow]:
    """Parse labels.csv text into rows; raises DatasetError if a needed column is missing."""
    reader = csv.DictReader(io.StringIO(csv_text))
    needed = {"photo_id", "file_name", "split", "readable", *LABEL_COLUMNS}
    missing = needed - set(reader.fieldnames or [])
    if missing:
        raise DatasetError(f"labels.csv is missing columns: {sorted(missing)}")
    rows = []
    for raw in reader:
        truth = {field: _truth_value(raw[column]) for column, field in LABEL_COLUMNS.items()}
        rows.append(
            LabelRow(
                photo_id=raw["photo_id"].strip(),
                file_name=raw["file_name"].strip(),
                split=raw["split"].strip(),
                readable=raw["readable"].strip().casefold() == "yes",
                truth={field: truth[field] for field in LABELLED_FIELDS},
            )
        )
    return rows


def load_tuning_labels(data_dir: Path) -> dict[str, LabelRow]:
    """Tuning rows of data_dir/labels.csv keyed by photo_id. Held-out rows are dropped unread."""
    labels_path = data_dir / "labels.csv"
    if not labels_path.is_file():
        raise DatasetError(f"labels.csv not found at {labels_path}; check AMBER_DATA_DIR")
    rows = parse_label_rows(labels_path.read_text(encoding="utf-8"))
    return {row.photo_id: row for row in rows if row.split == TUNING}


def ensure_not_heldout(path: Path) -> None:
    """Raise before any held-out path can be opened."""
    if any(part.casefold() == "heldout" for part in path.parts):
        raise DatasetError(f"refusing to touch a held-out path: {path}")


def tuning_photo_path(data_dir: Path, row: LabelRow) -> Path:
    """Path of a tuning photo; raises for non-tuning rows, held-out paths or missing files."""
    if row.split != TUNING:
        raise DatasetError(f"{row.photo_id} is in split {row.split!r}, not tuning")
    path = data_dir / "photos" / TUNING / row.file_name
    ensure_not_heldout(path)
    if not path.is_file():
        raise DatasetError(f"photo not found: {path}")
    return path
