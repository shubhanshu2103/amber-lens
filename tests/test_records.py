from pathlib import Path

import pytest

from amber_lens.records import RecordStore, normalise

RECORDS = Path(__file__).parent.parent / "data" / "records"


@pytest.fixture()
def store():
    return RecordStore.from_csv_dir(RECORDS)


def test_normalise():
    assert normalise("m-3538 ") == "M3538"
    assert normalise("FM 140156") == "FM140156"


def test_exact(store):
    hit = store.po_lines("M3538")
    assert hit and hit[0].match_type == "exact" and hit[0].record.model_number == "M3538"


def test_normalised(store):
    hit = store.po_lines("fm-140156")
    assert hit and hit[0].match_type == "normalised"


def test_fuzzy_is_only_a_hint(store):
    hit = store.po_lines("M353B")  # one OCR slip
    assert not hit or all(m.match_type == "fuzzy" for m in hit)


def test_no_match(store):
    assert store.po_lines("ZZZ-NOT-A-MODEL") == []
    assert store.submittal_for_model("ZZZ-NOT-A-MODEL") is None


def test_alias_from_allowed_suffix(store):
    store.db.execute("UPDATE submittals SET allowed_suffixes='-X' WHERE model_number='M3538'")
    hit = store.submittal_for_model("M3538-X")
    assert hit and hit.match_type == "alias"


def test_schedule_and_submittal(store):
    assert store.schedule_rows("M3538")[0].record.room_tag.startswith("R-")
    assert store.submittal_for_model("M3538").record.ratings["voltage"] == "230/460 V"


def test_po_line_by_number(store):
    line = store.po_line("PO-ALPHA-1001", 1)
    assert line and line.model_number == "M3538"
    assert store.po_line("PO-ALPHA-1001", 99) is None


def test_every_po_model_has_schedule_and_submittal(store):
    for m in store.po_lines.__self__.db.execute("SELECT model_number FROM po_lines"):
        assert store.schedule_rows(m[0]) and store.submittal_for_model(m[0])
