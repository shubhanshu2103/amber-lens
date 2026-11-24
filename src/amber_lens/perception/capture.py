"""Capture page (#10): phone photo + room QR tag -> saved photo and Observation JSON.

Run on the laptop, then open http://<laptop-ip>:8000 on a phone on the same wifi:
    uvicorn amber_lens.perception.capture:app --host 0.0.0.0 --port 8000

Privacy: no GPS, no names. Every photo is rebuilt from its pixels, so no metadata (EXIF, GPS) is kept,
and the page sends only a random device ID and a role. On top of the team rule (photograph labels only),
two layers keep people out: a required "No people in this photo" checkbox (the user's confirmation) and
the YuNet face detector (best-effort; it can miss faces and never sees people without a visible face).
A photo is rejected, and never saved, when the box is unticked or YuNet finds a face.
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import io
import re
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from amber_lens.perception.config import REPO_ROOT
from amber_lens.schemas import Observation

CAPTURE_DIR = REPO_ROOT / "captures"
PAGE = Path(__file__).with_name("capture.html")
ROLES = ("site engineer", "storekeeper", "quality inspector", "project manager")
ROOM_TAG = re.compile(r"[A-Z0-9][A-Z0-9.\-]{1,31}")
DETECT_MAX_SIDE = 800
MAX_BODY_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
FACE_MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
# YuNet's default score threshold; on the 35 tuning nameplates the highest face score was 0.53.
FACE_SCORE_THRESHOLD = 0.9
TagSource = Literal["qr_in_photo", "qr_photo", "typed"]


class CaptureRejected(ValueError):
    """The photo is refused and nothing is saved."""


class CaptureRequest(BaseModel):
    kind: Literal["nameplate", "crate_label", "delivery_ticket", "packing_slip"]
    role: Literal[ROLES]
    device_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    no_people_confirmed: bool
    photo_b64: str
    tag_photo_b64: str | None = None
    room_tag_typed: str | None = None


class CaptureResponse(BaseModel):
    observation: Observation
    room_tag_source: TagSource | None


def decode_image(b64: str) -> Image.Image:
    """Decode an upload, apply the camera's rotation and rebuild it from pixels so no metadata survives."""
    try:
        image = Image.open(io.BytesIO(base64.b64decode(b64, validate=True)))
        if image.width * image.height > MAX_PIXELS:
            raise CaptureRejected("The photo is over 40 megapixels. Retake it at a lower resolution.")
        image.load()
    except Image.DecompressionBombError as exc:
        raise CaptureRejected("The photo is too large to open. Retake it at a lower resolution.") from exc
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise CaptureRejected("That file is not a photo.") from exc
    upright = ImageOps.exif_transpose(image).convert("RGB")
    return Image.frombytes("RGB", upright.size, upright.tobytes())


@functools.lru_cache(maxsize=1)
def _face_detector():
    if hashlib.sha256(FACE_MODEL.read_bytes()).hexdigest() != FACE_MODEL_SHA256:
        raise RuntimeError(f"refusing to load {FACE_MODEL.name}: SHA-256 does not match the pinned hash")
    import cv2

    return cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (320, 320), FACE_SCORE_THRESHOLD)


def has_face(image: Image.Image) -> bool:
    """Best-effort: does YuNet find a face at or above FACE_SCORE_THRESHOLD?"""
    import cv2
    import numpy as np

    small = image.copy()
    small.thumbnail((DETECT_MAX_SIDE, DETECT_MAX_SIDE))
    detector = _face_detector()
    detector.setInputSize(small.size)
    _, faces = detector.detect(cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR))
    return faces is not None and len(faces) > 0


def decode_qr(image: Image.Image) -> str | None:
    import cv2
    import numpy as np

    text, _, _ = cv2.QRCodeDetector().detectAndDecode(np.asarray(image))
    return text.strip() or None


def room_tag(photo: Image.Image, tag_photo: Image.Image | None, typed: str | None) -> tuple[str | None, TagSource | None]:
    """QR in the photo first, then a QR in the second photo, then the typed tag; the tag must look like one."""
    candidates = (
        (decode_qr(photo), "qr_in_photo"),
        (decode_qr(tag_photo) if tag_photo is not None else None, "qr_photo"),
        ((typed or "").strip().upper() or None, "typed"),
    )
    for tag, source in candidates:
        if tag is not None:
            if not ROOM_TAG.fullmatch(tag):
                raise CaptureRejected(f"'{tag}' is not a room tag. Scan the room QR or type the tag.")
            return tag, source
    return None, None


def save_capture(request: CaptureRequest, directory: Path = CAPTURE_DIR) -> CaptureResponse:
    """Check, strip and save one capture; writes <id>.jpg and <id>.json and returns the Observation."""
    if not request.no_people_confirmed:
        raise CaptureRejected("Tick 'No people in this photo' after checking the frame.")
    photo = decode_image(request.photo_b64)
    tag_photo = decode_image(request.tag_photo_b64) if request.tag_photo_b64 else None
    if any(has_face(image) for image in (photo, tag_photo) if image is not None):
        raise CaptureRejected("A face was found in the photo. Retake it showing only the label.")
    tag, source = room_tag(photo, tag_photo, request.room_tag_typed)
    observation_id = f"obs-{uuid.uuid4().hex[:12]}"
    directory.mkdir(parents=True, exist_ok=True)
    photo_path = directory / f"{observation_id}.jpg"
    photo.save(photo_path, "JPEG", quality=92)
    observation = Observation(observation_id=observation_id, kind=request.kind, device_id=request.device_id,
                              role=request.role, room_tag=tag, photo_path=str(photo_path))
    response = CaptureResponse(observation=observation, room_tag_source=source)
    photo_path.with_suffix(".json").write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return response


app = FastAPI(title="Amber Lens capture")


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.post("/api/observations")
async def create_observation(request: Request) -> CaptureResponse:
    # Read the body in chunks so an oversize upload is refused before it is held in memory.
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="The upload is over 15 MB. Retake the photo at a lower resolution.")
    try:
        capture = CaptureRequest.model_validate_json(body)
    except ValidationError as exc:
        fields = ", ".join(str(error["loc"][-1]) for error in exc.errors() if error["loc"]) or "the body is not valid JSON"
        raise HTTPException(status_code=422, detail=f"The capture request is invalid ({fields}).") from exc
    try:
        return await run_in_threadpool(save_capture, capture)
    except CaptureRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
