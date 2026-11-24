# A. Perception

Reads equipment photos into shared `schemas.py` types: a vision model on Groq reads each field, and local
OCR (RapidOCR and Tesseract, on the CPU) must find the same characters on the photo before a field is READ.

| Module | What it does |
| --- | --- |
| `reader.py` | `read_nameplate(photo) -> PerceptionResult`, `run_nameplate` (result + reason codes + rule + locating path), `read_observation` |
| `capture.py`, `capture.html` | Phone capture page (#10): photo + room QR tag -> saved photo and Observation JSON |
| `models/` | YuNet face model (MIT, see `SOURCE.md`), SHA-256 checked before loading |
| `documents.py` | Crate labels and delivery tickets (#22): label anchors for every field, row-and-column rule for table cells; `read_observation` for every kind |
| `providers.py`, `groq.py` | Vision provider choice (`VISION_PROVIDER`: ollama or groq); Groq client with face check, rate limits and cache |
| `faces.py` | YuNet face check used by the capture page and before any cloud call |
| `fields.py` | Field names in `ReadField.name`: `model_number`, `catalog_number`, `voltage`, `rated_current`, `power`, `frequency`, `manufacturer` |
| `config.py` | Settings from the environment and `.env`: `AMBER_DATA_DIR`, `AMBER_CACHE_DIR`, `OLLAMA_HOST`, `VISION_MODEL_NAME` (default `qwen2.5vl:7b`) |
| `dataset.py` | Tuning rows of `labels.csv` and tuning photo paths; held-out paths are refused before they are opened |
| `cache.py` | Model responses cached on disk by image sha256, model name and prompt version |
| `vision.py` | Ollama client (temperature 0, fixed seed, JSON schema output), the reader and spike prompts, strict parsing that ignores unknown keys |
| `ocr.py` | Tesseract (9 passes) and RapidOCR adapters; words and lines with boxes in photo pixels |
| `crops.py` | Optional path, off by default: re-read the cells next to printed labels, padded and upscaled |
| `locate.py` | Finds a read value among OCR boxes; fragment, box-height, label-anchor and unit-adjacency checks |
| `injection.py` | Flags instruction-like label text and planted second MODEL labels (#12); flagged text is quoted evidence only |
| `textfields.py` | OCR-only field values by fixed label patterns (the second opinion, and rule R4's candidates) |
| `rules.py` | Format rules, printed-label list, power unit attachment |
| `scoring.py`, `evaluate.py` | Comparison with `labels.csv` and the tuning eval, for measurement only |
| `spike.py`, `check_sheet.py` | Reader spike (#8) and the label check sheet |

The full READ rule and its reason codes are in the `reader.py` docstring.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,ocr,capture]"     # Windows; use .venv/bin/python elsewhere
winget install --id UB-Mannheim.TesseractOCR -e          # or apt install tesseract-ocr
```

Put `GROQ_API_KEY` in `.env` (copy `.env.example`; never commit `.env`).

RapidOCR's ONNX models ship inside the `rapidocr` package, so no download happens at runtime.
`AMBER_DATA_DIR` defaults to `../amber-lens-data/data`, a read-only worktree of `d/dataset-hf-40`:

```bash
git worktree add --detach ../amber-lens-data origin/d/dataset-hf-40
```

Switch it to `./data` once the final `labels.csv` lands on `main`, then rerun the spike and the eval.

## Vision provider: Groq

`qwen/qwen3.8-27b` on Groq (`GROQ_MODEL`) is the default. Accuracy comes from the strict rule, not the model:
OCR must confirm every value on the photo, so on 94 labelled key values Groq has 3 key wrong READs and a local
7B model 2; two of Groq's three are cases the local model also gets wrong and one is a label gap. Groq answers
in about 1 s, so a check takes 5.3 s (local OCR sets the pace) against 15.8 s for the local model, and it needs
no GPU, so it deploys on a CPU-only server (`deploy/perception.env`).

- A photo is sent to Groq only after the on-device face check; a photo with a face is never sent.
- Calls stay inside 30 requests and 8K tokens per minute, wait on HTTP 429 `retry-after`, and are cached on
  disk, so reruns cost nothing. `cost_usd` is Groq's list price for the tokens used (about $0.0025 per check;
  the free tier charges nothing).
- If Groq fails (an error, rate limits beyond 3 retries, a removed model), every field from that photo is
  DISPUTED with reason `vision_unavailable` and `warnings["vision"]` says why; nothing is guessed.
- Risk: `qwen/qwen3.8-27b` is a Groq preview model and can be deprecated at short notice; the model is one setting.

## Offline mode: Ollama

`VISION_PROVIDER=ollama` runs `qwen2.5vl:7b` locally (`ollama pull qwen2.5vl:7b`, needs a GPU); photos never leave
the machine. `VISION_FALLBACK=ollama` keeps Groq primary and tries Ollama when Groq fails.

## Capture page and privacy

```bash
uvicorn amber_lens.perception.capture:app --host 0.0.0.0 --port 8000
```

Open `http://<laptop-ip>:8000` on a phone on the same wifi (allow Python on private networks when
Windows asks). Photos go to `captures/` (git-ignored) with a JSON sidecar.
The capture server has no authentication and is for a demo on a private or site network only; never run it on public Wi-Fi.

- No GPS, no names: every photo is rebuilt from its pixels, so EXIF and GPS never reach disk; the page
  sends only a random device ID and a role from a fixed list.
- People: the team rule (photograph labels only) comes first. On top of it, two layers: a required
  "No people in this photo" checkbox (the user's confirmation) and the YuNet face detector at score 0.9
  (best-effort: it can miss faces and cannot see people whose face is not visible). A photo is rejected
  and not saved if the box is unticked or a face is found. On the 35 tuning nameplates it rejected 0.
- Room tag: QR in the photo, else QR in a second photo, else typed. Only a decoded QR sets
  `tag_read_ok`; a typed tag is recorded as `typed`.

## How to run

```bash
python -m amber_lens.perception.reader ../amber-lens-data/data/photos/tuning/hf_038.jpg --out examples/perception_result_sample.json
python -m amber_lens.perception.evaluate --ocr both --json-out docs/perception_eval_tuning.json
python -m amber_lens.perception.spike --json-out docs/reader_spike_results.json
python -m amber_lens.perception.check_sheet --results docs/reader_spike_results.json
pytest -q tests/perception                      # local_model tests run only when Ollama is up
```

Unit tests replace the vision model and OCR with stand-ins and use fixtures in `tests/fixtures/perception/`,
so they need neither Ollama, Tesseract, RapidOCR nor the dataset worktree.
