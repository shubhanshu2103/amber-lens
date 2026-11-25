"""OCR adapters (Tesseract, RapidOCR): words and lines with pixel boxes in the original photo.

pytesseract and rapidocr come from the [ocr] extra and are imported only when an engine runs.
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

from amber_lens.schemas import BBox

WINDOWS_DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# Tesseract wants text around 20-30 px high; the dataset photos are 200-740 px wide.
TARGET_WIDTH_PX = 1800
MAX_UPSCALE = 6.0
PRIMARY_PASS = "psm11-gray"
RAPID_PASS = "rapidocr"
# Primary pass first (11 = sparse text), then block (6) and sparse-with-orientation (12) layouts, each on
# the grey image, an Otsu-binarised copy and its inverse (light text on dark plates).
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


def find_tesseract() -> str:
    """Path of the tesseract binary: PATH first, then the default Windows install."""
    found = shutil.which("tesseract")
    if found:
        return found
    if WINDOWS_DEFAULT_TESSERACT.is_file():
        return str(WINDOWS_DEFAULT_TESSERACT)
    raise OcrUnavailable("tesseract not found on PATH or in C:\\Program Files\\Tesseract-OCR")


def upscale_factor(width: int) -> float:
    return min(max(1.0, TARGET_WIDTH_PX / width), MAX_UPSCALE)


def otsu_threshold(histogram: list[int]) -> int:
    """Grey level that best splits a 256-bin histogram into two classes (Otsu's method)."""
    total = sum(histogram)
    weighted_total = sum(level * count for level, count in enumerate(histogram))
    background, weighted_background = 0, 0.0
    best_level, best_variance = 0, -1.0
    for level, count in enumerate(histogram):
        background += count
        weighted_background += level * count
        if background in (0, total):
            continue
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
    threshold = otsu_threshold(gray.histogram())
    binary = gray.point(lambda p: 255 if p > threshold else 0)
    return ImageOps.invert(binary) if variant == "inverted" else binary


def words_from_tesseract_data(
    data: dict, scale: float, image_size: tuple[int, int], offset: tuple[int, int] = (0, 0)
) -> list[OcrWord]:
    """pytesseract image_to_data output -> words with boxes in photo pixels (offset: top-left of a crop)."""
    width, height = image_size
    ox, oy = offset
    words = []
    for i, raw_text in enumerate(data["text"]):
        text = (raw_text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        x = min(ox + math.floor(data["left"][i] / scale), width - 1)
        y = min(oy + math.floor(data["top"][i] / scale), height - 1)
        right = min(ox + math.ceil((data["left"][i] + data["width"][i]) / scale), width)
        bottom = min(oy + math.ceil((data["top"][i] + data["height"][i]) / scale), height)
        line_key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        words.append(OcrWord(text, conf, BBox(x=x, y=y, w=max(right - x, 1), h=max(bottom - y, 1)), line_key))
    return words


def union_bbox(boxes: list[BBox]) -> BBox:
    x = min(b.x for b in boxes)
    y = min(b.y for b in boxes)
    return BBox(x=x, y=y, w=max(b.x + b.w for b in boxes) - x, h=max(b.y + b.h for b in boxes) - y)


def make_line(words: tuple[OcrWord, ...], pass_id: str) -> OcrLine:
    return OcrLine(" ".join(w.text for w in words), union_bbox([w.bbox for w in words]), words, pass_id)


def group_lines(words: list[OcrWord], pass_id: str = PRIMARY_PASS) -> list[OcrLine]:
    """Group words into Tesseract's lines, keeping reading order."""
    grouped: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        grouped.setdefault(word.line_key, []).append(word)
    return [make_line(tuple(group), pass_id) for group in grouped.values()]


def tesseract_module() -> ModuleType:
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable('pytesseract is not installed; pip install -e ".[ocr]"') from exc
    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    return pytesseract


def _read_passes(image_path: Path, passes: tuple[tuple[int, str], ...]) -> OcrResult:
    pytesseract = tesseract_module()
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
    pass_names = "+".join(f"psm{psm}-{variant}" for psm, variant in passes)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return OcrResult(f"tesseract {version} {pass_names}", tuple(lines), latency_ms)


def run_tesseract(image_path: Path, psm: int = 11) -> OcrResult:
    """One grey Tesseract pass, as used by the reader spike."""
    return _read_passes(image_path, ((psm, "gray"),))


def run_multipass(image_path: Path) -> OcrResult:
    """Every Tesseract pass in MULTIPASS over the full photo, lines tagged with their pass_id."""
    return _read_passes(image_path, MULTIPASS)


@functools.lru_cache(maxsize=1)
def rapidocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise OcrUnavailable('rapidocr is not installed; pip install -e ".[ocr]"') from exc
    return RapidOCR(params={"Global.log_level": "error"})


def quad_to_bbox(
    quad: list[list[float]], image_size: tuple[int, int], scale: float = 1.0, offset: tuple[int, int] = (0, 0)
) -> BBox:
    """Box around a 4-point polygon, mapped back from a scaled crop and clamped to the photo."""
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
    """RapidOCR word_results -> OcrLines; an unreadable line comes back flat as ('', score, None) and is skipped."""
    lines = []
    for index, detected in enumerate(word_results):
        items = (detected,) if detected and isinstance(detected[0], str) else detected
        words = tuple(
            OcrWord(text.strip(), float(score) * 100, quad_to_bbox(quad, image_size, scale, offset), (0, 0, index))
            for text, score, quad in (item for item in items if isinstance(item, (tuple, list)) and len(item) == 3)
            if text and text.strip() and quad is not None
        )
        if words:
            lines.append(make_line(words, pass_id))
    return lines


def run_rapidocr(image_path: Path) -> OcrResult:
    """RapidOCR over the full photo, with word boxes."""
    engine = rapidocr_engine()
    started = time.perf_counter()
    with Image.open(image_path) as image:
        size = image.size
    lines = lines_from_rapidocr(engine(str(image_path), return_word_box=True).word_results or (), size)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return OcrResult("rapidocr", tuple(lines), latency_ms, primary_pass=RAPID_PASS)


def combine(*results: OcrResult) -> OcrResult:
    """Lines of several engines in order; the first result's primary pass leads."""
    return OcrResult(
        " + ".join(r.engine for r in results),
        tuple(line for r in results for line in r.lines),
        sum(r.latency_ms for r in results),
        primary_pass=results[0].primary_pass,
    )


def run_rapidocr_and_tesseract(image_path: Path) -> OcrResult:
    """The reader's default: RapidOCR first, then every Tesseract pass."""
    return combine(run_rapidocr(image_path), run_multipass(image_path))
