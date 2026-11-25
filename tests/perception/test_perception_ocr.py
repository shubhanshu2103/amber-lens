import sys
from pathlib import Path

import pytest
from PIL import Image

from amber_lens.perception import ocr
from amber_lens.perception.ocr import (
    MULTIPASS,
    PRIMARY_PASS,
    RAPID_PASS,
    OcrLine,
    OcrResult,
    OcrUnavailable,
    combine,
    group_lines,
    lines_from_rapidocr,
    otsu_threshold,
    prepare,
    quad_to_bbox,
    upscale_factor,
    words_from_tesseract_data,
)
from amber_lens.schemas import BBox

DATA = {
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
BOX = BBox(x=0, y=0, w=1, h=1)


@pytest.mark.parametrize(
    ("scale", "size", "offset", "fx_box"),
    [
        (2.0, (200, 100), (0, 0), BBox(x=60, y=5, w=50, h=10)),
        (1.0, (150, 70), (0, 0), BBox(x=120, y=10, w=30, h=20)),
        (2.0, (400, 200), (100, 50), BBox(x=160, y=55, w=50, h=10)),
    ],
)
def test_tesseract_words_scaled_clamped_and_offset(scale, size, offset, fx_box) -> None:
    words = words_from_tesseract_data(DATA, scale=scale, image_size=size, offset=offset)
    assert [w.text for w in words] == ["MODEL", "FX-100A", "VOLTS"]
    assert words[1].bbox == fx_box


def test_group_lines_keeps_order_and_unions_boxes() -> None:
    lines = group_lines(words_from_tesseract_data(DATA, scale=1.0, image_size=(400, 200)))
    assert [line.text for line in lines] == ["MODEL FX-100A", "VOLTS"]
    assert lines[0].bbox == BBox(x=20, y=10, w=200, h=20)


@pytest.mark.parametrize(("width", "factor"), [(3600, 1.0), (900, 2.0), (10, ocr.MAX_UPSCALE)])
def test_upscale_factor(width: int, factor: float) -> None:
    assert upscale_factor(width) == factor


def test_otsu_and_prepare_variants() -> None:
    histogram = [0] * 256
    histogram[40] = histogram[200] = 100
    assert 40 <= otsu_threshold(histogram) < 200
    gray = Image.new("L", (4, 1))
    gray.putdata([10, 20, 220, 230])
    assert prepare(gray, "gray") is gray
    assert list(prepare(gray, "binary").tobytes()) == [0, 0, 255, 255]
    assert list(prepare(gray, "inverted").tobytes()) == [255, 255, 0, 0]


def test_multipass_starts_with_the_primary_pass() -> None:
    assert f"psm{MULTIPASS[0][0]}-{MULTIPASS[0][1]}" == PRIMARY_PASS
    assert len(set(MULTIPASS)) == 9


def test_quad_to_bbox_maps_back_and_clamps() -> None:
    quad = [[30, 15], [90, 15], [90, 45], [30, 45]]
    assert quad_to_bbox(quad, (200, 100)) == BBox(x=30, y=15, w=60, h=30)
    assert quad_to_bbox(quad, (200, 100), scale=3.0, offset=(100, 50)) == BBox(x=110, y=55, w=20, h=10)
    assert quad_to_bbox([[-5, -5], [500, -5], [500, 500], [-5, 500]], (200, 100)) == BBox(x=0, y=0, w=200, h=100)


def test_lines_from_rapidocr_skips_unreadable_entries() -> None:
    model = ("MODEL", 0.99, [[10, 10], [60, 10], [60, 30], [10, 30]])
    number = ("NO.", 0.98, [[65, 10], [90, 10], [90, 30], [65, 30]])
    word_results = ((model, number), (("  ", 0.5, [[0, 0], [1, 0], [1, 1], [0, 1]]),), ((),), ("", 1.0, None))
    lines = lines_from_rapidocr(word_results, (200, 100))
    assert [(line.text, line.pass_id, line.bbox) for line in lines] == [
        ("MODEL NO.", RAPID_PASS, BBox(x=10, y=10, w=80, h=20))
    ]


def test_combine_orders_lines_and_keeps_first_primary() -> None:
    first = OcrResult("rapidocr", (OcrLine("a", BOX, (), RAPID_PASS),), 10, primary_pass=RAPID_PASS)
    merged = combine(first, OcrResult("tesseract", (OcrLine("b", BOX, ()),), 20))
    assert [line.text for line in merged.lines] == ["a", "b"]
    assert (merged.latency_ms, merged.primary_pass, merged.engine) == (30, RAPID_PASS, "rapidocr + tesseract")


def test_find_tesseract_raises_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr, "WINDOWS_DEFAULT_TESSERACT", Path("Z:/no/such/tesseract.exe"))
    with pytest.raises(OcrUnavailable, match="not found"):
        ocr.find_tesseract()


@pytest.mark.parametrize(("module", "run"), [("pytesseract", ocr.run_tesseract), ("rapidocr", ocr.run_rapidocr)])
def test_engines_report_a_missing_package(monkeypatch, tmp_path: Path, module: str, run) -> None:
    monkeypatch.setitem(sys.modules, module, None)
    ocr.rapidocr_engine.cache_clear()
    with pytest.raises(OcrUnavailable, match=module):
        run(tmp_path / "x.png")
    ocr.rapidocr_engine.cache_clear()
