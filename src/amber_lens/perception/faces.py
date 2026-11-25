"""YuNet face check (best-effort): used by the capture page and before any photo is sent to a cloud model."""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path

from PIL import Image

FACE_MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
# YuNet's default score threshold; on the 35 tuning nameplates the highest face score was 0.53.
FACE_SCORE_THRESHOLD = 0.9
DETECT_MAX_SIDE = 800


class FaceInPhoto(RuntimeError):
    """A face was found, so the photo is not sent anywhere."""


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

    small = image.convert("RGB")
    small.thumbnail((DETECT_MAX_SIDE, DETECT_MAX_SIDE))
    detector = _face_detector()
    detector.setInputSize(small.size)
    _, faces = detector.detect(cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR))
    return faces is not None and len(faces) > 0
