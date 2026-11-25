from amber_lens.perception.ocr import OcrLine
from amber_lens.perception.textfields import TextHit, extract_fields
from amber_lens.schemas import BBox

BOX = BBox(x=0, y=0, w=10, h=10)


def _lines(*texts: str) -> list[OcrLine]:
    return [OcrLine(text=t, bbox=BOX, words=()) for t in texts]


def test_extracts_labelled_fields() -> None:
    hits = extract_fields(
        _lines("MODEL NO. FX-100A", "VOLTS 230/460 AMP. 7.8/3.9", "HP 3 Hz 60", "SERVICE FACTOR 1.15")
    )
    assert hits["model_number"] == TextHit("FX-100A", 0)
    assert hits["voltage"] == TextHit("230/460", 1)
    assert hits["rated_current"] == TextHit("7.8/3.9", 1)
    assert hits["power"] == TextHit("3 HP", 2)
    assert hits["frequency"] == TextHit("60", 2)


def test_unit_suffix_patterns() -> None:
    hits = extract_fields(_lines("400 V 28.5 A 15 kW 50 Hz"))
    assert hits["voltage"].value == "400"
    assert hits["rated_current"].value == "28.5"
    assert hits["power"].value == "15 KW"
    assert hits["frequency"].value == "50"


def test_nothing_found() -> None:
    hits = extract_fields(_lines("THERMALLY PROTECTED", ""))
    assert all(hit is None for hit in hits.values())


def test_catalog_and_order_numbers_are_their_own_field() -> None:
    hits = extract_fields(_lines("MODEL HLS447", "CAT. NO. HHI150-12", "ORD. NO. 3GBA18"))
    assert hits["model_number"] == TextHit("HLS447", 0)
    assert hits["catalog_number"] == TextHit("HHI150-12", 1)
    assert extract_fields(_lines("ORD. NO. 3GBA18"))["catalog_number"] == TextHit("3GBA18", 0)
