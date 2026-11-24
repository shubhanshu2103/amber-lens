"""OCR adapters (Tesseract and RapidOCR): words and lines with pixel boxes in the original photo.

pytesseract and rapidocr are optional dependencies ([ocr] extra) and are imported only inside
_tesseract and _rapidocr_engine, so the rest of perception imports and tests without them.
RapidOCR ships its ONNX models inside the package, so it needs no network at runtime.
"""

from __future__ import annotations

import functools
import math
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from PIL import Image, ImageOps

from amber_lens.perception.rules import PRINTED_LABELS, label_key
from amber_lens.schemas import BBox

WINDOWS_DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# Tesseract wants text around 20-30 px high; the dataset photos are 200-740 px wide.
TARGET_WIDTH_PX = 1800
MAX_UPSCALE = 6.0
# Page segmentation 11 = sparse text, which suits table-like nameplates.
DEFAULT_PSM = 11
PRIMARY_PASS = "psm11-gray"
RAPID_PASS = "rapidocr"
# Multi-pass order: the primary pass first, then block (6) and sparse-with-orientation (12) layouts,
# each on the grey image, an Otsu-binarised copy and its inverse (light text on dark plates).
MULTIPASS: tuple[tuple[int, str], ...] = tuple(
    (psm, variant) for variant in ("gray", "binary", "inverted") for psm in (11, 6, 12)
)


class OcrUnavailable(RuntimeError):
    """The OCR engine is not installed or cannot run."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    conf: float
    bbox: BBox
    line_key: tuple[int, int, int]


@dataclass(frozen=True)
class OcrLine:
    text: str
    bbox: BBox
    words: tuple[OcrWord, ...]
    pass_id: str = PRIMARY_PASS


@dataclass(frozen=True)
class OcrResult:
    engine: str
    lines: tuple[OcrLine, ...]
    latency_ms: int
    # The pass whose reading under printed labels counts as "OCR's own reading" of a field.
    primary_pass: str = PRIMARY_PASS

    def pass_lines(self, pass_id: str) -> tuple[OcrLine, ...]:
        return tuple(line for line in self.lines if line.pass_id == pass_id)


def find_tesseract() -> str:
    found = shutil.which("tesseract")
    if found:
        return found
    if WINDOWS_DEFAULT_TESSERACT.is_file():
        return str(WINDOWS_DEFAULT_TESSERACT)
    raise OcrUnavailable("tesseract not found on PATH or in C:\\Program Files\\Tesseract-OCR")


def upscale_factor(width: int) -> float:
    if width <= 0:
        raise ValueError("image width must be positive")
    return min(max(1.0, TARGET_WIDTH_PX / width), MAX_UPSCALE)


def otsu_threshold(histogram: list[int]) -> int:
    """Grey level that best separates a 256-bin histogram into two classes (Otsu's method)."""
    if len(histogram) != 256:
        raise ValueError("histogram must have 256 bins")
    total = sum(histogram)
    if total == 0:
        raise ValueError("histogram is empty")
    weighted_total = sum(level * count for level, count in enumerate(histogram))
    background = 0
    weighted_background = 0.0
    best_level, best_variance = 0, -1.0
    for level, count in enumerate(histogram):
        background += count
        if background == 0 or background == total:
            continue
        weighted_background += level * count
        mean_bg = weighted_background / background
        mean_fg = (weighted_total - weighted_background) / (total - background)
        variance = background * (total - background) * (mean_bg - mean_fg) ** 2
        if variance > best_variance:
            best_level, best_variance = level, variance
    return best_level


def prepare(gray: Image.Image, variant: str) -> Image.Image:
    """The image a pass reads: grey as is, Otsu-binarised, or binarised and inverted."""
    if variant == "gray":
        return gray
    if variant not in ("binary", "inverted"):
        raise ValueError(f"unknown OCR variant: {variant!r}")
    threshold = otsu_threshold(gray.histogram())
    binary = gray.point(lambda p: 255 if p > threshold else 0)
    return ImageOps.invert(binary) if variant == "inverted" else binary


def _to_original(value: float, scale: float) -> int:
    return math.floor(value / scale)


def words_from_tesseract_data(
    data: dict, scale: float, image_size: tuple[int, int], offset: tuple[int, int] = (0, 0)
) -> list[OcrWord]:
    """Convert pytesseract image_to_data output (dict form) into words with boxes in original pixels.

    offset is the top-left of the region that was read, when only a crop of the photo was OCR'd.
    """
    width, height = image_size
    ox, oy = offset
    words = []
    for i, raw_text in enumerate(data["text"]):
        text = (raw_text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        x = min(ox + _to_original(data["left"][i], scale), width - 1)
        y = min(oy + _to_original(data["top"][i], scale), height - 1)
        right = min(ox + math.ceil((data["left"][i] + data["width"][i]) / scale), width)
        bottom = min(oy + math.ceil((data["top"][i] + data["height"][i]) / scale), height)
        words.append(
            OcrWord(
                text=text,
                conf=conf,
                bbox=BBox(x=x, y=y, w=max(right - x, 1), h=max(bottom - y, 1)),
                line_key=(int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i])),
            )
        )
    return words


def union_bbox(boxes: list[BBox]) -> BBox:
    if not boxes:
        raise ValueError("cannot take the union of no boxes")
    x = min(b.x for b in boxes)
    y = min(b.y for b in boxes)
    right = max(b.x + b.w for b in boxes)
    bottom = max(b.y + b.h for b in boxes)
    return BBox(x=x, y=y, w=right - x, h=bottom - y)


def group_lines(words: list[OcrWord], pass_id: str = PRIMARY_PASS) -> list[OcrLine]:
    """Group words into Tesseract's lines, keeping reading order."""
    order: list[tuple[int, int, int]] = []
    grouped: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        if word.line_key not in grouped:
            order.append(word.line_key)
            grouped[word.line_key] = []
        grouped[word.line_key].append(word)
    return [
        OcrLine(
            text=" ".join(w.text for w in grouped[key]),
            bbox=union_bbox([w.bbox for w in grouped[key]]),
            words=tuple(grouped[key]),
            pass_id=pass_id,
        )
        for key in order
    ]


def _tesseract() -> ModuleType:
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable('pytesseract is not installed; pip install -e ".[ocr]"') from exc
    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    return pytesseract


def _read_passes(image_path: Path, passes: tuple[tuple[int, str], ...]) -> OcrResult:
    pytesseract = _tesseract()
    started = time.perf_counter()
    with Image.open(image_path) as image:
        gray = ImageOps.grayscale(image)
        size = image.size
    scale = upscale_factor(size[0])
    resized = gray.resize((round(size[0] * scale), round(size[1] * scale)), Image.Resampling.LANCZOS)
    lines: list[OcrLine] = []
    try:
        for psm, variant in passes:
            data = pytesseract.image_to_data(
                prepare(resized, variant), config=f"--psm {psm}", output_type=pytesseract.Output.DICT
            )
            lines.extend(group_lines(words_from_tesseract_data(data, scale, size), pass_id=f"psm{psm}-{variant}"))
        version = str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractError as exc:
        raise OcrUnavailable(f"tesseract failed on {image_path.name}: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    pass_names = "+".join(f"psm{psm}-{variant}" for psm, variant in passes)
    return OcrResult(engine=f"tesseract {version} {pass_names}", lines=tuple(lines), latency_ms=latency_ms)


def run_tesseract(image_path: Path, psm: int = DEFAULT_PSM) -> OcrResult:
    """One grey pass, as used by the reader spike. Raises OcrUnavailable when Tesseract is missing."""
    return _read_passes(image_path, ((psm, "gray"),))


def run_multipass(image_path: Path) -> OcrResult:
    """Every pass in MULTIPASS over the full photo; lines from all passes, tagged with their pass_id."""
    return _read_passes(image_path, MULTIPASS)


@functools.lru_cache(maxsize=1)
def _rapidocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise OcrUnavailable('rapidocr is not installed; pip install -e ".[ocr]"') from exc
    return RapidOCR(params={"Global.log_level": "error"})


def quad_to_bbox(
    quad: list[list[float]], image_size: tuple[int, int], scale: float = 1.0, offset: tuple[int, int] = (0, 0)
) -> BBox:
    """Axis-aligned box around a 4-point polygon, mapped back from a scaled crop and clamped to the image."""
    width, height = image_size
    xs = [offset[0] + p[0] / scale for p in quad]
    ys = [offset[1] + p[1] / scale for p in quad]
    x = min(max(math.floor(min(xs)), 0), width - 1)
    y = min(max(math.floor(min(ys)), 0), height - 1)
    right = min(math.ceil(max(xs)), width)
    bottom = min(math.ceil(max(ys)), height)
    return BBox(x=x, y=y, w=max(right - x, 1), h=max(bottom - y, 1))


def lines_from_rapidocr(
    word_results: tuple, image_size: tuple[int, int], scale: float = 1.0, offset: tuple[int, int] = (0, 0),
    pass_id: str = RAPID_PASS,
) -> list[OcrLine]:
    """Convert RapidOCR word_results (one tuple of (text, score, quad) per detected line) into OcrLines.

    A line RapidOCR detected but could not read comes back flat, as ('', score, None); entries without
    text or without a box are skipped.
    """
    lines = []
    for index, detected in enumerate(word_results):
        items = (detected,) if detected and isinstance(detected[0], str) else detected
        words = tuple(
            OcrWord(text=text.strip(), conf=float(score) * 100, bbox=quad_to_bbox(quad, image_size, scale, offset),
                    line_key=(0, 0, index))
            for text, score, quad in (item for item in items if isinstance(item, (tuple, list)) and len(item) == 3)
            if text and text.strip() and quad is not None
        )
        if words:
            lines.append(OcrLine(text=" ".join(w.text for w in words), bbox=union_bbox([w.bbox for w in words]),
                                 words=words, pass_id=pass_id))
    return lines


def run_rapidocr(image_path: Path) -> OcrResult:
    """RapidOCR (PP-OCR models on ONNX Runtime) over the full photo, with word boxes."""
    engine = _rapidocr_engine()
    started = time.perf_counter()
    with Image.open(image_path) as image:
        size = image.size
    output = engine(str(image_path), return_word_box=True)
    lines = lines_from_rapidocr(output.word_results or (), size)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return OcrResult(engine="rapidocr", lines=tuple(lines), latency_ms=latency_ms, primary_pass=RAPID_PASS)


def combine(*results: OcrResult) -> OcrResult:
    """Lines of several engines in the given order; the first result's primary pass leads."""
    if not results:
        raise ValueError("nothing to combine")
    return OcrResult(
        engine=" + ".join(r.engine for r in results),
        lines=tuple(line for r in results for line in r.lines),
        latency_ms=sum(r.latency_ms for r in results),
        primary_pass=results[0].primary_pass,
    )


def run_rapidocr_and_tesseract(image_path: Path) -> OcrResult:
    """RapidOCR first, then every Tesseract pass; a value may be located by either engine."""
    return combine(run_rapidocr(image_path), run_multipass(image_path))


CROP_PASS = "crop_ocr"
# Path B: the cell right of and below every printed label is cropped, padded, upscaled and read again.
CROP_PAD = 0.2
CROP_UPSCALE = 3.0
CROP_RIGHT_HEIGHTS = 10
CROP_BELOW_HEIGHTS = 6
MAX_CROPS = 24


def _iou(a: BBox, b: BBox) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    return inter / (a.w * a.h + b.w * b.h - inter) if inter else 0.0


def _padded(x: float, y: float, w: float, h: float, image_size: tuple[int, int]) -> BBox | None:
    width, height = image_size
    x0 = max(0, math.floor(x - CROP_PAD * w))
    y0 = max(0, math.floor(y - CROP_PAD * h))
    x1 = min(width, math.ceil(x + w + CROP_PAD * w))
    y1 = min(height, math.ceil(y + h + CROP_PAD * h))
    return BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0) if x1 - x0 >= 4 and y1 - y0 >= 4 else None


def label_cells(lines: tuple[OcrLine, ...] | list[OcrLine], image_size: tuple[int, int]) -> list[BBox]:
    """Padded cells right of and below each printed label OCR found; one-letter labels are skipped."""
    keys = {k for labels in PRINTED_LABELS.values() for k in labels if len(k) > 1}
    cells: list[BBox] = []
    for line in lines:
        words = line.words
        for i in range(len(words)):
            for j in range(i, min(i + 3, len(words))):
                if label_key(" ".join(w.text for w in words[i : j + 1])) not in keys:
                    continue
                box = union_bbox([w.bbox for w in words[i : j + 1]])
                for cell in (
                    _padded(box.x + box.w, box.y - 0.3 * box.h, CROP_RIGHT_HEIGHTS * box.h, 1.6 * box.h, image_size),
                    _padded(box.x - box.h, box.y + box.h, box.w + CROP_BELOW_HEIGHTS * box.h, 2 * box.h, image_size),
                ):
                    if cell is not None and all(_iou(cell, other) < 0.5 for other in cells):
                        cells.append(cell)
    return cells[:MAX_CROPS]


def _read_crops(image_path: Path, cells: list[BBox], use_rapidocr: bool) -> list[OcrLine]:
    pytesseract = _tesseract()
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        size = image.size
    lines: list[OcrLine] = []
    for cell in cells:
        crop = rgb.crop((cell.x, cell.y, cell.x + cell.w, cell.y + cell.h))
        big = crop.resize((round(cell.w * CROP_UPSCALE), round(cell.h * CROP_UPSCALE)), Image.Resampling.LANCZOS)
        origin = (cell.x, cell.y)
        data = pytesseract.image_to_data(ImageOps.grayscale(big), config="--psm 6",
                                         output_type=pytesseract.Output.DICT)
        lines.extend(group_lines(words_from_tesseract_data(data, CROP_UPSCALE, size, origin), pass_id=CROP_PASS))
        if use_rapidocr:
            import numpy as np

            output = _rapidocr_engine()(np.asarray(big), return_word_box=True)
            lines.extend(lines_from_rapidocr(output.word_results or (), size, CROP_UPSCALE, origin, CROP_PASS))
    return lines


def with_crops(base: OcrResult, image_path: Path, use_rapidocr: bool) -> OcrResult:
    """Add path B: OCR of the padded, upscaled cells next to every label the base OCR found."""
    started = time.perf_counter()
    with Image.open(image_path) as image:
        size = image.size
    lines = _read_crops(image_path, label_cells(base.lines, size), use_rapidocr)
    crops = OcrResult(engine="crop_ocr", lines=tuple(lines), latency_ms=int((time.perf_counter() - started) * 1000))
    return combine(base, crops)


def run_tesseract_with_crops(image_path: Path) -> OcrResult:
    return with_crops(run_multipass(image_path), image_path, use_rapidocr=False)


def run_both_with_crops(image_path: Path) -> OcrResult:
    return with_crops(run_rapidocr_and_tesseract(image_path), image_path, use_rapidocr=True)


OCR_RUNNERS = {
    "tesseract": run_multipass,
    "rapidocr": run_rapidocr,
    "both": run_rapidocr_and_tesseract,
    "tesseract+crops": run_tesseract_with_crops,
    "both+crops": run_both_with_crops,
}
