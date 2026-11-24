"""Optional OCR path (off by default): re-read the cells next to every printed label, padded and upscaled."""

from __future__ import annotations

import math
import time
from pathlib import Path

from PIL import Image, ImageOps

from amber_lens.perception.locate import label_boxes
from amber_lens.perception.ocr import (
    OcrLine,
    OcrResult,
    combine,
    group_lines,
    lines_from_rapidocr,
    rapidocr_engine,
    run_multipass,
    run_rapidocr_and_tesseract,
    tesseract_module,
    words_from_tesseract_data,
)
from amber_lens.perception.rules import PRINTED_LABELS
from amber_lens.schemas import BBox

CROP_PASS = "crop_ocr"
CROP_PAD = 0.2
CROP_UPSCALE = 3.0
MAX_CROPS = 24
LABEL_KEYS = {k for labels in PRINTED_LABELS.values() for k in labels if len(k) > 1}


def _iou(a: BBox, b: BBox) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    return inter / (a.w * a.h + b.w * b.h - inter) if inter else 0.0


def _padded(x: float, y: float, w: float, h: float, image_size: tuple[int, int]) -> BBox | None:
    x0, y0 = max(0, math.floor(x - CROP_PAD * w)), max(0, math.floor(y - CROP_PAD * h))
    x1 = min(image_size[0], math.ceil(x + w + CROP_PAD * w))
    y1 = min(image_size[1], math.ceil(y + h + CROP_PAD * h))
    return BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0) if x1 - x0 >= 4 and y1 - y0 >= 4 else None


def label_cells(lines: tuple[OcrLine, ...] | list[OcrLine], image_size: tuple[int, int]) -> list[BBox]:
    """Padded cells right of and below each printed label OCR found; one-letter labels are skipped."""
    cells: list[BBox] = []
    for box in label_boxes(lines, LABEL_KEYS):
        right = _padded(box.x + box.w, box.y - 0.3 * box.h, 10 * box.h, 1.6 * box.h, image_size)
        below = _padded(box.x - box.h, box.y + box.h, box.w + 6 * box.h, 2 * box.h, image_size)
        for cell in (right, below):
            if cell is not None and all(_iou(cell, other) < 0.5 for other in cells):
                cells.append(cell)
    return cells[:MAX_CROPS]


def with_crops(base: OcrResult, image_path: Path, use_rapidocr: bool) -> OcrResult:
    """base plus OCR of every label cell, lines tagged crop_ocr."""
    pytesseract = tesseract_module()
    started = time.perf_counter()
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        size = image.size
    lines: list[OcrLine] = []
    for cell in label_cells(base.lines, size):
        crop = rgb.crop((cell.x, cell.y, cell.x + cell.w, cell.y + cell.h))
        big = crop.resize((round(cell.w * CROP_UPSCALE), round(cell.h * CROP_UPSCALE)), Image.Resampling.LANCZOS)
        origin = (cell.x, cell.y)
        data = pytesseract.image_to_data(ImageOps.grayscale(big), config="--psm 6",
                                         output_type=pytesseract.Output.DICT)
        lines.extend(group_lines(words_from_tesseract_data(data, CROP_UPSCALE, size, origin), pass_id=CROP_PASS))
        if use_rapidocr:
            import numpy as np

            output = rapidocr_engine()(np.asarray(big), return_word_box=True)
            lines.extend(lines_from_rapidocr(output.word_results or (), size, CROP_UPSCALE, origin, CROP_PASS))
    crops = OcrResult("crop_ocr", tuple(lines), int((time.perf_counter() - started) * 1000))
    return combine(base, crops)


def run_tesseract_with_crops(image_path: Path) -> OcrResult:
    return with_crops(run_multipass(image_path), image_path, use_rapidocr=False)


def run_both_with_crops(image_path: Path) -> OcrResult:
    return with_crops(run_rapidocr_and_tesseract(image_path), image_path, use_rapidocr=True)
