# Task T4: capture page, photo + room QR -> Observation (#10)

Owner: A Perception (Vrushali). Not committed yet.

## "Done when" (#10)

| Item | Status | Evidence |
| --- | --- | --- |
| works from a phone on the same wifi | **done from the laptop over the LAN IP; phone test is yours** | `GET http://192.168.1.4:8000/` -> 200; POST with a QR in the photo -> 200, room tag `ELEC-2.04` (`qr_in_photo`); unticked box -> 422 |
| saves photo + returns Observation JSON | **done** | `captures/<id>.jpg` + `<id>.json` sidecar; response is `{"observation": Observation, "room_tag_source": ...}` |

To test on a phone: run `uvicorn amber_lens.perception.capture:app --host 0.0.0.0 --port 8000`, allow
Python on private networks when Windows asks, open `http://192.168.1.4:8000` on a phone on the same wifi.

## What was built and why

- `capture.py` (153 lines): one FastAPI app with `GET /` (the page) and `POST /api/observations`.
  The upload is JSON with base64 images, so no extra upload library is needed.
- No GPS, no names: the photo is rebuilt from its pixels (`Image.frombytes`), so no EXIF or GPS can
  survive; a test saves a GPS-tagged JPEG and checks the stored file has no EXIF. The request accepts only
  a random UUIDv4 device ID and a role from a fixed list; `role="Vrushali"` is rejected.
- People, two layers on top of the team rule: the required "No people in this photo" checkbox, and the
  YuNet face detector. Rejected photos are never saved, with a short message for each case.
- Room tag: QR in the photo, else QR in a second photo, else typed; the tag must look like a room tag.
  The sidecar records the source; `read_observation` sets `tag_read_ok` only for a decoded QR, never for a
  typed tag (change in `reader.py`).
- `capture.html` (101 lines): mobile-first, plain JS, no CDN. The device ID comes from
  `crypto.getRandomValues`, because `crypto.randomUUID` needs HTTPS and the site wifi is plain http.

## Limits (follow-up fixes before the commit)

- Request body capped at 15 MB, read in chunks: HTTP 413 with a short message. Live: a 16 MB body -> 413.
- Photos over 40 megapixels are refused from the header before decoding; Pillow's DecompressionBombError
  is caught. Both come back as HTTP 422 with a message, never a 500. An invalid or non-JSON request -> 422.
- The page shows "Could not reach the laptop" only when the request itself fails; any other failure shows
  the HTTP status and the server's detail.
- README: the server has no authentication; demo on a private or site network only, never public Wi-Fi.

## Decisions (your answers)

| Id | Answer | Outcome |
| --- | --- | --- |
| T4-1 | A: FastAPI + plain HTML, QR in photo / second photo / typed, metadata stripped, UUID + role | built |
| T4-2 | OpenCV detectors + checkbox | OpenCV 5.1 (installed by RapidOCR) has no Haar cascades or HOG detector |
| T4-3/4 | measured: OpenCV defaults rejected 14 of 35 nameplates; OpenCV 4 cost 1 correct reader value | B chosen |
| T4-4 | B: OpenCV 5 + YuNet, SHA-256 pinned, 0 false rejections, checkbox kept, no pin, no HOG | done |

## Measurements

- YuNet false rejections on the 35 tuning nameplates at the default score threshold 0.9: **0**. The
  highest face score on any nameplate was 0.531 (hf_092), so the threshold stays at YuNet's default.
- Recall on real faces is not measured: our rule forbids photos of people, so the detector stays
  best-effort and the checkbox is the user's confirmation.
- Back on OpenCV 5 the 35-photo reader eval is identical to the committed run, field by field
  (41 key values READ and correct, 5 wrong READs).
- QR: a tag made by OpenCV's encoder and pasted on a synthetic label decodes as `ELEC-2.04`.

## Correction

I said earlier that YuNet is Apache-2.0. Its model folder carries its own **MIT** licence (Copyright 2020
Shiqi Yu); the zoo repository as a whole is Apache-2.0. The committed `models/LICENSE_YUNET` is the real
MIT text, and `models/SOURCE.md` has the source URL, retrieval date and SHA-256.

## Draft for Koushik (#13 / rooms.csv; post on "post")

> The capture page reads the room QR as the plain `room_tag` string, e.g. `ELEC-2.04`, and accepts tags
> matching `[A-Z0-9][A-Z0-9.-]{1,31}`. Can you confirm this matches the `room_tag` column in `rooms.csv`
> (uppercase, no spaces)? If so, we can print one QR per room from that column for the demo.

## Exact run commands

```bash
.venv/Scripts/ruff check .
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn amber_lens.perception.capture:app --host 0.0.0.0 --port 8000
```

Output: `All checks passed!`; `218 passed`.

## Gaps and risks

- Not tested on a real phone yet; iPhone photos sent as HEIC would be refused as "not a photo" (Safari
  usually converts camera captures to JPEG).
- The face detector cannot see people without a visible face; the checkbox and the team rule cover that.
- `capture.html` and the model file sit inside the package; an editable install finds them, but a
  non-editable install (Docker, #33) needs `package-data` in pyproject. Note for Koushik.
- Whoever reaches the laptop on the wifi can post captures; there is no login. Demo on a private or site
  network only (README).

## Files added or changed

Added: `src/amber_lens/perception/capture.py`, `capture.html`, `models/face_detection_yunet_2023mar.onnx`,
`models/LICENSE_YUNET`, `models/SOURCE.md`, `tests/perception/test_perception_capture.py`, this report.
Changed: `pyproject.toml` (new `capture = ["opencv-python-headless"]` extra, no pin),
`src/amber_lens/perception/reader.py` (`read_observation` tag rule), `src/amber_lens/perception/README.md`,
`tests/perception/test_perception_reader.py`.

## Size

capture.py 171 lines (largest function 18), capture.html 108, tests 137 (13 tests), SOURCE.md 10;
reader.py +5. Cut: HOG person detector, OpenCV pin, login, image resizing, upload library.

## Proposed commit

`a: capture page with metadata stripping, face check and room QR (#10)`; stage the files above.
