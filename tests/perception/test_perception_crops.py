from amber_lens.perception.crops import label_cells
from amber_lens.perception.ocr import OcrLine, OcrWord
from amber_lens.schemas import BBox


def _line(text: str, box: BBox) -> OcrLine:
    return OcrLine(text, box, (OcrWord(text=text, conf=90.0, bbox=box, line_key=(1, 1, 1)),))


def test_label_cells_right_and_below_without_duplicates_or_one_letter_labels() -> None:
    volts = _line("VOLTS", BBox(x=20, y=20, w=50, h=10))
    cells = label_cells([volts, volts, _line("V", BBox(x=20, y=60, w=8, h=10))], (400, 200))
    assert len(cells) == 2
    right, below = cells
    assert right.x < 70 < right.x + right.w and right.y < 20
    # The padded cell below starts just above the label's bottom edge.
    assert 20 < below.y < 30 < below.y + below.h
