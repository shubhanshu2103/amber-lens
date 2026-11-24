# A. Perception

Reads equipment photos into shared `schemas.py` types. Everything runs locally: a vision model via
Ollama plus Tesseract and RapidOCR, so `cost_usd` is 0.0.

| Module | What it does |
| --- | --- |
| `reader.py` | `read_nameplate(photo) -> PerceptionResult`, `run_nameplate` (result + reason codes + rule + locating path), `read_observation` |
| `fields.py` | Field names in `ReadField.name`: `model_number`, `catalog_number`, `voltage`, `rated_current`, `power`, `frequency`, `manufacturer` |
| `config.py` | Settings from the environment and `.env`: `AMBER_DATA_DIR`, `AMBER_CACHE_DIR`, `OLLAMA_HOST`, `VISION_MODEL_NAME` (default `qwen2.5vl:7b`) |
| `dataset.py` | Tuning rows of `labels.csv` and tuning photo paths; held-out paths are refused before they are opened |
| `cache.py` | Model responses cached on disk by image sha256, model name and prompt version |
| `vision.py` | Ollama client (temperature 0, fixed seed, JSON schema output), the reader and spike prompts, strict parsing that ignores unknown keys |
| `ocr.py` | Tesseract (9 passes) and RapidOCR adapters, label-anchored crops; words and lines with boxes in photo pixels |
| `locate.py` | Finds a read value among OCR boxes; fragment, box-height, label-anchor and unit-adjacency checks |
| `textfields.py` | OCR-only field values by fixed label patterns (the second opinion, and rule R4's candidates) |
| `rules.py` | Format rules, printed-label list, power unit attachment |
| `scoring.py`, `evaluate.py` | Comparison with `labels.csv` and the tuning eval, for measurement only |
| `spike.py`, `check_sheet.py` | Reader spike (#8) and the label check sheet |

The full READ rule and its reason codes are in the `reader.py` docstring.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,ocr]"     # Windows; use .venv/bin/python elsewhere
winget install --id UB-Mannheim.TesseractOCR -e          # or apt install tesseract-ocr
ollama pull qwen2.5vl:7b
```

RapidOCR's ONNX models ship inside the `rapidocr` package, so no download happens at runtime.
`AMBER_DATA_DIR` defaults to `../amber-lens-data/data`, a read-only worktree of `d/dataset-hf-40`:

```bash
git worktree add --detach ../amber-lens-data origin/d/dataset-hf-40
```

Switch it to `./data` once the final `labels.csv` lands on `main`, then rerun the spike and the eval.

## How to run

```bash
python -m amber_lens.perception.reader ../amber-lens-data/data/photos/tuning/hf_038.jpg --out examples/perception_result_sample.json
python -m amber_lens.perception.evaluate --ocr both --json-out docs/perception_eval_tuning.json
python -m amber_lens.perception.spike --json-out docs/reader_spike_results.json
python -m amber_lens.perception.check_sheet --results docs/reader_spike_results.json
pytest -q tests/perception
```

Unit tests replace the vision model and OCR with stand-ins and use fixtures in `tests/fixtures/perception/`,
so they need neither Ollama, Tesseract, RapidOCR nor the dataset worktree.
