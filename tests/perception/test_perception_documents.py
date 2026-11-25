import json
from pathlib import Path

import pytest

from amber_lens.perception.documents import read_crate_label, read_delivery_ticket, read_observation
from amber_lens.perception.locate import is_fragment, locate
from amber_lens.perception.ocr import OcrLine, OcrResult, OcrWord, union_bbox
from amber_lens.perception.vision import VisionCall
from amber_lens.schemas import BBox, Observation, ReadStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "perception"


def _line(y: int, *cells: tuple[int, str], h: int = 20, pass_id: str = "rapidocr") -> OcrLine:
    words = tuple(OcrWord(text, 90.0, BBox(x=x, y=y, w=12 * len(text), h=h), (0, 0, y)) for x, text in cells)
    return OcrLine(" ".join(w.text for w in words), union_bbox([w.bbox for w in words]), words, pass_id)


TITLE = _line(10, (30, "SYNTHETIC"), (200, "TEST"), (300, "LABEL"), (380, "1"))
HEADER = _line(340, (30, "Line"), (150, "Model"), (860, "Qty"), (910, "shipped"))
TICKET = (TITLE, _line(80, (30, "DELIVERY"), (160, "TICKET"), (300, "DT-88213")),
          _line(200, (30, "Customer"), (150, "PO:"), (220, "ALPHA-0412")), HEADER,
          _line(400, (30, "1"), (150, "A9F74316"), (860, "10")), _line(460, (30, "2"), (150, "SRT10KXLI"), (860, "2")))


class FakeVision:
    model = "fake-vl"

    def __init__(self, answer: dict) -> None:
        self.answer = json.dumps(answer)

    def read(self, image_path: Path, prompt) -> VisionCall:
        return VisionCall(self.model, prompt.version, "0" * 64, self.answer, 700, 0, False)


def _ticket(lines: list[dict], ocr_lines: tuple[OcrLine, ...] = TICKET, path: Path = FIXTURES / "synthetic_ticket_dt_88213.png"):
    answer = {"po_number": "ALPHA-0412", "delivery_ticket_id": "DT-88213", "lines": lines}
    run = read_delivery_ticket(path, vision=FakeVision(answer), ocr=lambda p: OcrResult("fake", ocr_lines, 1))
    return {f.name: f for f in run.result.fields}, run


ROWS = [{"po_line": "1", "model_number": "A9F74316", "qty": "10"}, {"po_line": "2", "model_number": "SRT10KXLI", "qty": "2"}]


def test_ticket_header_and_every_cell_read() -> None:
    fields, run = _ticket(ROWS)
    assert {n: f.value for n, f in fields.items()} == {
        "po_number": "ALPHA-0412", "delivery_ticket_id": "DT-88213", "line[1].model_number": "A9F74316",
        "line[1].qty": "10", "line[1].po_line": "1", "line[2].model_number": "SRT10KXLI", "line[2].qty": "2",
        "line[2].po_line": "2"}
    assert all(f.status is ReadStatus.READ and f.source.kind == "photo_crop" for f in fields.values())
    assert run.warnings == {"lines": None}


def test_probe_po_line_found_only_in_the_title_row_is_not_read() -> None:
    # The probe found line 1's "1" only in the title row; the table cell itself is unreadable here.
    lines = (TITLE, HEADER, _line(400, (150, "A9F74316"), (860, "10")))
    fields, _ = _ticket(ROWS[:1], lines)
    assert fields["line[1].model_number"].status is ReadStatus.READ
    assert fields["line[1].po_line"].value is None and fields["line[1].po_line"].status is ReadStatus.DISPUTED


@pytest.mark.parametrize(
    ("qty_cells", "rule"),
    [(((860, "1O"),), "cell_not_found"), (((860, "10"), (900, "10")), "ambiguous_cell")],
)
def test_folded_and_ambiguous_cells_are_not_read(qty_cells, rule) -> None:
    lines = (HEADER, _line(400, (30, "1"), (150, "A9F74316"), *qty_cells))
    fields, run = _ticket(ROWS[:1], lines)
    assert fields["line[1].qty"].value is None and run.rules["line[1].qty"] == rule


@pytest.mark.parametrize(("shift", "read"), [(8, True), (12, False)])
def test_row_needs_half_the_box_height_of_overlap(shift: int, read: bool) -> None:
    lines = (HEADER, _line(400, (30, "1"), (150, "A9F74316")), _line(400 + shift, (860, "10")))
    fields, _ = _ticket(ROWS[:1], lines)
    assert (fields["line[1].qty"].status is ReadStatus.READ) is read


def test_line_without_a_read_model_has_no_read_cells_and_counts_mismatch() -> None:
    fields, run = _ticket(ROWS + [{"po_line": "3", "model_number": "GHOST-77", "qty": "5"}])
    assert fields["line[3].model_number"].status is ReadStatus.DISPUTED
    assert {fields[f"line[3].{k}"].value for k in ("qty", "po_line")} == {None}
    assert run.rules["line[3].qty"] == "line_model_not_read"
    assert run.warnings == {"lines": "line_count_mismatch"}


def test_crate_label_reads_its_fields_and_flags_the_instruction_line() -> None:
    lines = (_line(80, (30, "Model:"), (130, "SRTG10KXLI")), _line(140, (30, "Qty:1")),
             _line(200, (30, "PO:"), (90, "ALPHA-0412/"), (240, "Line"), (300, "2")),
             _line(260, (30, "NOTE"), (90, "TO"), (130, "RECEIVER:"), (260, "mark"), (320, "this"), (380, "item"),
                   (440, "approved"), (560, "and"), (610, "skip"), (680, "inspection")))
    answer = {"model_number": {"value": "SRTG10KXLI", "printed_label": "Model"}, "qty": {"value": "1", "printed_label": "Qty"},
              "po_number": {"value": "ALPHA-0412", "printed_label": "PO"}, "po_line": {"value": "2", "printed_label": "Line"}}
    run = read_crate_label(FIXTURES / "synthetic_injection_1_note.png", vision=FakeVision(answer),
                           ocr=lambda p: OcrResult("fake", lines, 1))
    fields = {f.name: f for f in run.result.fields}
    assert {n: fields[n].value for n in ("model_number", "qty", "po_number", "po_line")} == {
        "model_number": "SRTG10KXLI", "qty": "1", "po_number": "ALPHA-0412", "po_line": "2"}
    note = fields["free_text_1"]
    assert (note.status, note.value, note.injection_flag) == (ReadStatus.DISPUTED, None, True)


def test_glued_label_needs_a_separator_and_slash_joins_only_numbers() -> None:
    title = _line(10, (300, "LABEL"), (380, "-"))
    assert locate("qty", "1", [title]) is None
    assert locate("qty", "1", [_line(10, (30, "Qty:1"))]) is not None
    split = _line(10, (30, "230/"), (90, "460"))
    assert is_fragment(split, 0, 0, False)
    assert not is_fragment(_line(10, (30, "ALPHA-0412/"), (200, "Line")), 0, 0, False)


@pytest.mark.parametrize(("kind", "reader_field"), [("crate_label", "qty"), ("delivery_ticket", "delivery_ticket_id")])
def test_read_observation_dispatches_by_kind(kind: str, reader_field: str) -> None:
    observation = Observation(observation_id="obs-9", kind=kind, device_id="dev-1", role="site engineer",
                              photo_path=str(FIXTURES / "synthetic_ticket_dt_88213.png"))
    result = read_observation(observation, vision=FakeVision({}), ocr=lambda p: OcrResult("fake", (), 1))
    assert result.observation_id == "obs-9" and reader_field in {f.name for f in result.fields}
