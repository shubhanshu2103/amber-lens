from pathlib import Path

import pytest

from amber_lens.perception.documents import read_crate_label, read_delivery_ticket
from amber_lens.schemas import ReadStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "perception"


@pytest.mark.local_model
def test_srt_crate_label_fields_read_and_instruction_flagged() -> None:
    fields = {f.name: f for f in read_crate_label(FIXTURES / "synthetic_injection_1_note.png").result.fields}
    assert {n: fields[n].value for n in ("model_number", "qty", "po_number", "po_line")} == {
        "model_number": "SRTG10KXLI", "qty": "1", "po_number": "ALPHA-0412", "po_line": "2"}
    flagged = [f for f in fields.values() if f.injection_flag]
    assert len(flagged) == 1 and flagged[0].status is ReadStatus.DISPUTED and flagged[0].value is None
    assert "NOTE TO RECEIVER" in flagged[0].ocr_value


@pytest.mark.local_model
def test_synthetic_ticket_lines_read() -> None:
    run = read_delivery_ticket(FIXTURES / "synthetic_ticket_dt_88213.png")
    assert {f.name: f.value for f in run.result.fields} == {
        "po_number": "ALPHA-0412", "delivery_ticket_id": "DT-88213", "line[1].model_number": "A9F74316",
        "line[1].qty": "10", "line[1].po_line": "1", "line[2].model_number": "SRT10KXLI", "line[2].qty": "2",
        "line[2].po_line": "2"}
    assert run.warnings == {"lines": None}
