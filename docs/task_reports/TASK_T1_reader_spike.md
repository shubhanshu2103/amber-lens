# Task T1: reader spike, vision model vs OCR (#8)

Owner: A Perception (Vrushali). Branch `a/perception`, based on `origin/main` at `918bb49`.

## "Done when" from #8

| Item | Status | Evidence |
| --- | --- | --- |
| small table of results in a comment here | **not done**: drafted below, posted only on your word "post" (decision T1-7 B) | "Draft comments" section |
| pick a model and say why | **done, pending your confirmation** (DECISION T1-8) | `docs/reader_spike.md`, "Recommendation" |

## What was built and why

- A local reader stack: `vision.py` calls Ollama with temperature 0, a fixed seed and a JSON schema, and
  `parse_reading` keeps only the expected keys with string values. Unknown keys are ignored, so label text
  cannot add fields. `ocr.py` gives Tesseract words and lines with boxes in original photo pixels.
- `rules.py` holds the format rules (standard voltages per IEC 60038 / NEMA, current range, frequency,
  power with a unit, model number shape). `locate.py` finds a read value among the OCR word boxes; this
  is the strict READ condition from T2-1 and is reused in T2.
- `spike.py` runs four arms (vision, vision+rule, vision+rule+located, OCR alone) on 10 tuning photos,
  with counts per field and latency per photo. `scoring.py` is for measurement only.
- `dataset.py` returns only `split == tuning` rows and refuses any path containing `heldout` before it
  is opened. `cache.py` caches model responses by image sha256, model and prompt version.
- `check_sheet.py` writes a local HTML page (`.cache/perception/check_sheet.html`, 10 photos): photo,
  label values and reader values side by side, a choice per field, and CSV export so a person can turn
  "agreement" into accuracy in about 10 minutes.

## Decisions (your answers)

| Id | Answer |
| --- | --- |
| T1-1 | A + B: pulled qwen2.5vl:3b and qwen3-vl:4b, one model at a time. Both misread more than 2 of 10 model numbers (3 and 3, plus 4 empty answers for qwen3-vl), so C was triggered: qwen2.5vl:7b pulled and run |
| T1-2 | A + B. `rapidocr-onnxruntime`'s current release (1.4.4) requires Python < 3.13; only the stale 1.2.3 installs. Went with Tesseract as instructed. Not added to pyproject. (The renamed package `rapidocr` 3.10 does support 3.13; see T2-3) |
| T1-3 | A: `.venv` on Python 3.13, code kept 3.11-compatible (ruff target py311). **Shared file: `pyproject.toml` moves `pillow>=10` from the `[ocr]` extra into core dependencies.** `pytesseract` is imported only inside `run_tesseract` |
| T1-4 | A + two: `model_number, voltage, rated_current, power, frequency, manufacturer`, values exactly as printed with whitespace collapsed. Comment for #13 and #15 drafted below |
| T1-5 | A: scored as "agreement with AI-read labels"; check sheet built; re-check list below |
| T1-6 | A: `.cache/` in `.gitignore`; `OLLAMA_HOST` and `AMBER_CACHE_DIR` in `.env.example` |
| T1-7 | B: nothing posted; drafts below |

## Results (10 photos x 3 key fields = 30; counts)

| Arm | correct | wrong READs | missed | s/photo mean |
| --- | --- | --- | --- | --- |
| vision qwen2.5vl:3b | 17 | 13 | 0 | 2.25 |
| vision+rule qwen2.5vl:3b | 17 | 12 | 1 | 2.25 |
| vision+rule+located qwen2.5vl:3b | 5 | 2 | 19 | 2.69 |
| vision qwen2.5vl:7b | 21 | 9 | 0 | 6.85 |
| vision+rule qwen2.5vl:7b | 20 | 8 | 2 | 6.85 |
| vision+rule+located qwen2.5vl:7b | 5 | 1 | 20 | 7.29 |
| vision qwen3-vl:4b | 9 | 6 | 12 | 36.87 |
| ocr (Tesseract 5.4.0) | 3 | 3 | 20 | 0.45 |

Cost $0.00 per photo for every arm. GPU share: 3b and qwen3-vl 100%, 7b 57% (6 GB card). Full per-field
tables, every disagreement and the unparseable answers are in `docs/reader_spike.md`.

Main findings: the format rule alone barely helps; every model invents a full plate for the unreadable
`hf_295`, and only the "located on the photo" condition stops that; example values in a prompt get copied
(fixed in prompt v3, which has no digits); with Tesseract, the strict rule keeps only 5 of 30 key values.

## Exact run commands

```bash
.venv/Scripts/ruff check .
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m amber_lens.perception.spike --models qwen2.5vl:3b qwen2.5vl:7b qwen3-vl:4b --json-out docs/reader_spike_results.json
.venv/Scripts/python -m amber_lens.perception.check_sheet --results docs/reader_spike_results.json
```

Output: `ruff check .` -> `All checks passed!`; `pytest -q` -> `134 passed in 2.82s` (11 existing + 123
new). A rerun from cache reproduces every count; only the live Tesseract latencies move by a few hundredths of a second.

Data comes from the read-only worktree `../amber-lens-data` (detached at `d843d58`, `d/dataset-hf-40`).
**When Vikas's final `labels.csv` lands on `main`, set `AMBER_DATA_DIR=./data` and rerun the spike.**

## Labels to re-check (for Vikas)

The reader disagrees with the label and either reading could be right. These are not counted as label errors.

1. `hf_02` model_number: `DI0034PCI` vs `DIO034PCI` (digit 0 or letter O after "DI").
2. `hf_04` model_number: `HHI150-12-447T` vs `HH1150-12-447T` (I or 1; the row's own notes say the dataset OCR also read `HH1150`). The plate also prints MODEL `HLS447SR0608`.
3. `hf_066`: model `MY90L-4` vs `MY80L-4`; two models read a current `5.40 A` where the label has none; voltage `230 V` vs `230 / 460 V`.
4. `hf_053`: qwen2.5vl:7b reads `15/18 kW` and `50/60 Hz`. Is the plate dual-rated? The label records only 50 Hz / 15 kW. This matters for the 50 vs 60 Hz substitution demo.
5. `darjja_train_10` rated_current: label `12.8 A (compressor RLA)`, readers `12.5 FLA` and `17.0 AMPS`. Confirm which current the label should carry.
6. `hf_259`: a multi-voltage plate (qwen2.5vl:7b lists six voltage rows); the label keeps one row (`400 Δ V`, `28.5 A`). Confirm which row is "the" rating.
7. `hf_06` model_number: qwen2.5vl:7b read `37J776T859G1`, label `094914` (Cat. No.). Same identifier question as `hf_04`.

## Gaps and risks

- **Truth is AI-read.** No person has used the check sheet yet; every "correct" is agreement only.
- **10 photos.** The model choice rests on 1 vs 2 wrong READs after locating; T2 reruns on all 35.
- **Coverage under the strict rule is 5 of 30** with Tesseract on these small photos. Without better
  locating, most fields come out DISPUTED and most verdicts CANT_MATCH, which hurts GO coverage (DECISION T2-3).
- Locating folds O/0, I/1, S/5, B/8, Z/2 to find the box, so it cannot settle cases like `hf_02` and
  `hf_04`. The T2 contradiction check compares the raw OCR text.
- Short rating values can be located in the wrong cell (`hf_053` current `15`). The fix is planned for T2: a short value only counts as located next to its unit or label.
- The scoring's dash and decimal-comma folding was added after the first run showed qwen3-vl writing `–`
  and `15.5` for `-` and `15,5`. It applies to every arm alike and is documented in `scoring.py`.
- qwen2.5vl:7b spills 43% to the CPU on this 6 GB card; latency on a different machine will differ.
- `ReadField` has no field for the reason codes you asked for in T2-1 (DECISION T2-5).
- T0 (#1, #2 outreach drafts) has not been started. You said to proceed with T1; T0 can follow T2 if you agree.

## What a reviewer from another workstream should check

- `dataset.py`: held-out rows are dropped and held-out paths raise before any file access.
- `vision.py` `parse_reading`: only expected keys, only strings; anything else becomes None.
- `rules.py` `STANDARD_VOLTAGES`: the list and its sources (420 is deliberately absent, so `hf_069`'s `380/420 Δ/Δ V` fails the rule).
- `scoring.py`: that the comparison key is fair and cannot hide a wrong digit.
- `pyproject.toml`: Pillow moving to core.

## For other owners

- Koushik (#13): use the field keys above in `Submittal.ratings`; the normaliser should fold units, dash styles and decimal commas.
- Shubhanshu (#15, #16): same keys. Reason codes and the reader contract arrive with T2.
- Vikas (D): the re-check list above, the check sheet, and the `AMBER_DATA_DIR` switch once labels land on `main`.
- Everyone: `pip install -e ".[dev]"` now pulls Pillow.

## Draft comments (post on "post")

**#8**

> Reader spike on 10 tuning photos, all local ($0.00 per photo). Counts are agreement with AI-read labels; a human check of these 10 rows is pending.
>
> | Arm (30 key values) | correct | wrong READs | s/photo |
> | --- | --- | --- | --- |
> | vision qwen2.5vl:3b | 17 | 13 | 2.3 |
> | vision+rule qwen2.5vl:3b | 17 | 12 | 2.3 |
> | vision+rule+located qwen2.5vl:3b | 5 | 2 | 2.7 |
> | vision qwen2.5vl:7b | 21 | 9 | 6.9 |
> | vision+rule qwen2.5vl:7b | 20 | 8 | 6.9 |
> | vision+rule+located qwen2.5vl:7b | 5 | 1 | 7.3 |
> | vision qwen3-vl:4b (thinking) | 9 | 6 | 36.9 |
> | Tesseract alone | 3 | 3 | 0.5 |
>
> Pick: qwen2.5vl:7b (fewest wrong READs, most correct), with qwen2.5vl:3b as the fast fallback. The format rule alone barely helps, and every model invents a full plate for an unreadable photo. A READ therefore needs the format rule **and** the value found on the photo by OCR; that removed every invented value. Next: raise OCR coverage without loosening the rule. Details in `docs/reader_spike.md`.

**#13 and #15**

> Perception emits `ReadField.name` = `model_number`, `voltage`, `rated_current`, `power`, `frequency`, `manufacturer`. Values are copied exactly as printed with whitespace collapsed, units as printed, e.g. `230/460 V`, `15,5 A / 18,0 A`, `1.0 HP (0.75 kW)`. Perception does no unit conversion or alias handling; that belongs in the records normaliser (#13). Please use the same keys in `Submittal.ratings` (instead of e.g. `hp`). The spike shows models change dash style and decimal commas freely, so the normaliser should fold those. Non-READ fields have `value = None` and a reason code (`format_fail`, `readers_disagree`, `not_located`, `model_missing`); where that code lives is being settled for #11.

## Files added or changed

Changed: `.env.example`, `.gitignore`, `pyproject.toml`

Added:
- `src/amber_lens/perception/README.md`, `fields.py`, `config.py`, `dataset.py`, `cache.py`, `vision.py`, `ocr.py`, `textfields.py`, `rules.py`, `scoring.py`, `locate.py`, `spike.py`, `check_sheet.py`
- `tests/fixtures/perception/labels_sample.csv`
- `tests/perception/test_perception_config.py`, `test_perception_dataset.py`, `test_perception_cache.py`, `test_perception_vision.py`, `test_perception_ocr.py`, `test_perception_rules.py`, `test_perception_textfields.py`, `test_perception_scoring.py`, `test_perception_locate.py`, `test_perception_spike.py`, `test_perception_check_sheet.py`
- `docs/reader_spike.md`, `docs/reader_spike_results.json`, `docs/task_reports/TASK_T1_reader_spike.md`

## Proposed commit

Message: `a: reader spike, vision vs OCR on 10 tuning photos (#8)`

Stage exactly:

```
.env.example .gitignore pyproject.toml
src/amber_lens/perception/README.md src/amber_lens/perception/fields.py src/amber_lens/perception/config.py
src/amber_lens/perception/dataset.py src/amber_lens/perception/cache.py src/amber_lens/perception/vision.py
src/amber_lens/perception/ocr.py src/amber_lens/perception/textfields.py src/amber_lens/perception/rules.py
src/amber_lens/perception/scoring.py src/amber_lens/perception/locate.py src/amber_lens/perception/spike.py
src/amber_lens/perception/check_sheet.py
tests/fixtures/perception/labels_sample.csv
tests/perception/test_perception_config.py tests/perception/test_perception_dataset.py
tests/perception/test_perception_cache.py tests/perception/test_perception_vision.py
tests/perception/test_perception_ocr.py tests/perception/test_perception_rules.py
tests/perception/test_perception_textfields.py tests/perception/test_perception_scoring.py
tests/perception/test_perception_locate.py tests/perception/test_perception_spike.py
tests/perception/test_perception_check_sheet.py
docs/reader_spike.md docs/reader_spike_results.json docs/task_reports/TASK_T1_reader_spike.md
```
