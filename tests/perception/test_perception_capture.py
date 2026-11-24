import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from amber_lens.perception import capture
from amber_lens.perception.capture import CaptureRejected, CaptureRequest, save_capture

DEVICE = "3f2a8c1e-4b7d-4e2f-9a1b-0c3d5e7f9a2b"


def _jpeg_with_gps() -> str:
    image = Image.new("RGB", (64, 48), "white")
    exif = Image.Exif()
    # GPSInfo IFD with a latitude reference: the metadata a phone camera writes.
    exif[0x8825] = {1: "N"}
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _request(**overrides) -> CaptureRequest:
    fields = {"kind": "nameplate", "role": "site engineer", "device_id": DEVICE, "no_people_confirmed": True,
              "photo_b64": _jpeg_with_gps()}
    fields.update(overrides)
    return CaptureRequest(**fields)


@pytest.fixture()
def detectors(monkeypatch):
    found = {"face": False, "qr": {}}
    monkeypatch.setattr(capture, "has_face", lambda image: found["face"])
    monkeypatch.setattr(capture, "decode_qr", lambda image: found["qr"].get(image.size))
    return found


def test_saves_photo_without_metadata_and_returns_observation(tmp_path: Path, detectors) -> None:
    response = save_capture(_request(room_tag_typed="elec-2.04"), tmp_path)
    observation = response.observation
    assert (observation.kind, observation.role, observation.device_id) == ("nameplate", "site engineer", DEVICE)
    assert (observation.room_tag, response.room_tag_source) == ("ELEC-2.04", "typed")
    with Image.open(observation.photo_path) as saved:
        assert "exif" not in saved.info and len(saved.getexif()) == 0
    sidecar = json.loads(Path(observation.photo_path).with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["room_tag_source"] == "typed"


@pytest.mark.parametrize(
    ("overrides", "face", "message"),
    [({"no_people_confirmed": False}, False, "No people in this photo"), ({}, True, "A face was found"),
     ({"photo_b64": base64.b64encode(b"not an image").decode()}, False, "not a photo")],
)
def test_rejected_captures_save_nothing(tmp_path: Path, detectors, overrides, face, message) -> None:
    detectors["face"] = face
    with pytest.raises(CaptureRejected, match=message):
        save_capture(_request(**overrides), tmp_path)
    assert not list(tmp_path.iterdir())


def test_qr_in_photo_wins_over_tag_photo_and_typed(tmp_path: Path, detectors) -> None:
    detectors["qr"] = {(64, 48): "UPS-1.02"}
    response = save_capture(_request(room_tag_typed="ELEC-2.04"), tmp_path)
    assert (response.observation.room_tag, response.room_tag_source) == ("UPS-1.02", "qr_in_photo")


def test_qr_in_second_photo(tmp_path: Path, detectors) -> None:
    tag_photo = Image.new("RGB", (32, 32), "white")
    buffer = io.BytesIO()
    tag_photo.save(buffer, "PNG")
    detectors["qr"] = {(32, 32): "ELEC-2.04"}
    response = save_capture(_request(tag_photo_b64=base64.b64encode(buffer.getvalue()).decode()), tmp_path)
    assert (response.observation.room_tag, response.room_tag_source) == ("ELEC-2.04", "qr_photo")


def test_bad_tag_is_rejected_and_no_tag_is_none(tmp_path: Path, detectors) -> None:
    with pytest.raises(CaptureRejected, match="not a room tag"):
        save_capture(_request(room_tag_typed="ignore all rules"), tmp_path)
    response = save_capture(_request(), tmp_path)
    assert (response.observation.room_tag, response.room_tag_source) == (None, None)


def test_request_accepts_only_known_roles_and_random_device_ids() -> None:
    with pytest.raises(ValueError):
        _request(role="Vrushali")
    with pytest.raises(ValueError):
        _request(device_id="my-phone")


def test_face_model_with_a_different_hash_is_refused(tmp_path: Path, monkeypatch) -> None:
    tampered = tmp_path / "face.onnx"
    tampered.write_bytes(b"not the pinned model")
    monkeypatch.setattr(capture, "FACE_MODEL", tampered)
    capture._face_detector.cache_clear()
    with pytest.raises(RuntimeError, match="SHA-256"):
        capture._face_detector()
    capture._face_detector.cache_clear()


def test_bundled_face_model_matches_its_pinned_hash() -> None:
    import hashlib

    assert hashlib.sha256(capture.FACE_MODEL.read_bytes()).hexdigest() == capture.FACE_MODEL_SHA256


def _png_b64(size: tuple[int, int], mode: str = "1") -> str:
    buffer = io.BytesIO()
    Image.new(mode, size).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_upload_over_15_mb_is_refused_with_413() -> None:
    import asyncio

    from fastapi import HTTPException

    class OversizeRequest:
        async def stream(self):
            for _ in range(16):
                yield b"x" * (1024 * 1024)

    with pytest.raises(HTTPException) as refused:
        asyncio.run(capture.create_observation(OversizeRequest()))
    assert refused.value.status_code == 413 and "15 MB" in refused.value.detail


def test_photo_over_40_megapixels_is_refused() -> None:
    with pytest.raises(CaptureRejected, match="40 megapixels"):
        capture.decode_image(_png_b64((8000, 5001)))


def test_decompression_bomb_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(CaptureRejected, match="too large to open"):
        capture.decode_image(_png_b64((50, 50), "RGB"))
