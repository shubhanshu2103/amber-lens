import sys
from pathlib import Path

import pytest

from amber_lens.perception import ocr
from amber_lens.perception.ocr import (
    OcrUnavailable,
    OcrWord,
    group_lines,
    union_bbox,
    upscale_factor,
    words_from_tesseract_data,
)
from amber_lens.schemas import BBox


def _data(**overrides) -> dict:
    data = {
        "text": ["MODEL", "", "FX-100A", "VOLTS", "noise"],
        "conf": [95, -1, 90, 88, -1],
        "left": [20, 0, 120, 20, 0],
        "top": [10, 0, 10, 60, 0],
        "width": [80, 0, 100, 60, 5],
        "height": [20, 0, 20, 20, 5],
        "block_num": [1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 2, 2],
    }
    data.update(overrides)
    return data


def test_words_are_scaled_back_and_filtered() -> None:
    words = words_from_tesseract_data(_data(), scale=2.0, image_size=(200, 100))
    assert [w.text for w in words] == ["MODEL", "FX-100A", "VOLTS"]
    assert words[1].bbox == BBox(x=60, y=5, w=50, h=10)


def test_words_are_clamped_to_the_image() -> None:
    words = words_from_tesseract_data(_data(), scale=1.0, image_size=(150, 70))
    fx = words[1]
    assert fx.bbox.x + fx.bbox.w <= 150
    volts = words[2]
    assert volts.bbox.y + volts.bbox.h <= 70


def test_group_lines_keeps_order_and_unions_boxes() -> None:
    lines = group_lines(words_from_tesseract_data(_data(), scale=1.0, image_size=(400, 200)))
    assert [line.text for line in lines] == ["MODEL FX-100A", "VOLTS"]
    assert lines[0].bbox == BBox(x=20, y=10, w=200, h=20)


def test_union_of_nothing_raises() -> None:
    with pytest.raises(ValueError):
        union_bbox([])


def test_upscale_factor_bounds() -> None:
    assert upscale_factor(3600) == 1.0
    assert upscale_factor(900) == 2.0
    assert upscale_factor(10) == ocr.MAX_UPSCALE
    with pytest.raises(ValueError):
        upscale_factor(0)


def test_find_tesseract_raises_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr, "WINDOWS_DEFAULT_TESSERACT", Path("Z:/no/such/tesseract.exe"))
    with pytest.raises(OcrUnavailable, match="not found"):
        ocr.find_tesseract()


def test_run_tesseract_needs_pytesseract(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(OcrUnavailable, match="pytesseract"):
        ocr.run_tesseract(tmp_path / "x.png")


def test_ocr_word_is_hashable_value() -> None:
    word = OcrWord(text="A", conf=1.0, bbox=BBox(x=0, y=0, w=1, h=1), line_key=(1, 1, 1))
    assert word == OcrWord(text="A", conf=1.0, bbox=BBox(x=0, y=0, w=1, h=1), line_key=(1, 1, 1))


def test_otsu_threshold_splits_two_levels() -> None:
    from amber_lens.perception.ocr import otsu_threshold

    histogram = [0] * 256
    histogram[40] = 100
    histogram[200] = 100
    assert 40 <= otsu_threshold(histogram) < 200
    with pytest.raises(ValueError):
        otsu_threshold([0] * 256)
    with pytest.raises(ValueError):
        otsu_threshold([1] * 10)


def test_prepare_variants() -> None:
    from PIL import Image

    from amber_lens.perception.ocr import prepare

    gray = Image.new("L", (4, 1))
    gray.putdata([10, 20, 220, 230])
    assert prepare(gray, "gray") is gray
    assert list(prepare(gray, "binary").tobytes()) == [0, 0, 255, 255]
    assert list(prepare(gray, "inverted").tobytes()) == [255, 255, 0, 0]
    with pytest.raises(ValueError, match="unknown OCR variant"):
        prepare(gray, "sepia")


def test_multipass_order_starts_with_the_primary_pass() -> None:
    from amber_lens.perception.ocr import MULTIPASS, PRIMARY_PASS

    assert f"psm{MULTIPASS[0][0]}-{MULTIPASS[0][1]}" == PRIMARY_PASS
    assert len(MULTIPASS) == 9 and len(set(MULTIPASS)) == 9


def test_pass_lines_filters_by_pass() -> None:
    from amber_lens.perception.ocr import OcrLine, OcrResult

    box = BBox(x=0, y=0, w=1, h=1)
    result = OcrResult("t", (OcrLine("a", box, (), "psm11-gray"), OcrLine("b", box, (), "psm6-binary")), 1)
    assert [line.text for line in result.pass_lines("psm6-binary")] == ["b"]


def test_quad_to_bbox_maps_back_from_a_scaled_crop() -> None:
    from amber_lens.perception.ocr import quad_to_bbox

    quad = [[30, 15], [90, 15], [90, 45], [30, 45]]
    assert quad_to_bbox(quad, (200, 100)) == BBox(x=30, y=15, w=60, h=30)
    assert quad_to_bbox(quad, (200, 100), scale=3.0, offset=(100, 50)) == BBox(x=110, y=55, w=20, h=10)
    assert quad_to_bbox([[-5, -5], [500, -5], [500, 500], [-5, 500]], (200, 100)) == BBox(x=0, y=0, w=200, h=100)


def test_lines_from_rapidocr_keeps_words_and_pass() -> None:
    from amber_lens.perception.ocr import RAPID_PASS, lines_from_rapidocr

    word_results = (
        (("MODEL", 0.99, [[10, 10], [60, 10], [60, 30], [10, 30]]), ("NO.", 0.98, [[65, 10], [90, 10], [90, 30], [65, 30]])),
        (("  ", 0.5, [[0, 0], [1, 0], [1, 1], [0, 1]]),),
        ((),),
        ("", 1.0, None),
    )
    lines = lines_from_rapidocr(word_results, (200, 100))
    assert len(lines) == 1
    assert lines[0].text == "MODEL NO." and lines[0].pass_id == RAPID_PASS
    assert lines[0].bbox == BBox(x=10, y=10, w=80, h=20)


def test_words_from_tesseract_data_with_offset() -> None:
    words = words_from_tesseract_data(_data(), scale=2.0, image_size=(400, 200), offset=(100, 50))
    assert words[1].bbox == BBox(x=160, y=55, w=50, h=10)


def test_combine_orders_lines_and_keeps_first_primary() -> None:
    from amber_lens.perception.ocr import RAPID_PASS, OcrLine, OcrResult, combine

    box = BBox(x=0, y=0, w=1, h=1)
    a = OcrResult("rapidocr", (OcrLine("a", box, (), RAPID_PASS),), 10, primary_pass=RAPID_PASS)
    b = OcrResult("tesseract", (OcrLine("b", box, ()),), 20)
    merged = combine(a, b)
    assert [line.text for line in merged.lines] == ["a", "b"]
    assert (merged.latency_ms, merged.primary_pass, merged.engine) == (30, RAPID_PASS, "rapidocr + tesseract")
    with pytest.raises(ValueError):
        combine()


def test_label_cells_right_and_below_without_duplicates() -> None:
    from amber_lens.perception.ocr import OcrLine, label_cells

    word = OcrWord(text="VOLTS", conf=90.0, bbox=BBox(x=20, y=20, w=50, h=10), line_key=(1, 1, 1))
    line = OcrLine("VOLTS", word.bbox, (word,))
    single = OcrWord(text="V", conf=90.0, bbox=BBox(x=20, y=60, w=8, h=10), line_key=(1, 1, 2))
    cells = label_cells([line, line, OcrLine("V", single.bbox, (single,))], (400, 200))
    assert len(cells) == 2
    right, below = cells
    assert right.x < 70 < right.x + right.w and right.y < 20
    # The padded cell below starts just above the label's bottom edge.
    assert 20 < below.y < 30 < below.y + below.h


def test_run_rapidocr_needs_rapidocr(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    ocr._rapidocr_engine.cache_clear()
    with pytest.raises(OcrUnavailable, match="rapidocr"):
        ocr.run_rapidocr(tmp_path / "x.png")
    ocr._rapidocr_engine.cache_clear()
