# Task T2: nameplate reader -> PerceptionResult (#11)

Owner: A Perception (Vrushali). Branch `a/perception`, based on `origin/main` at `918bb49`. T1 is not
committed yet; T2 builds on it in the same working tree (see "Proposed commits").

## "Done when"

| Item | Status | Evidence |
| --- | --- | --- |
| #11: runs on all tuning photos without crashing | **done** | `evaluate` read 35 of 35 tuning photos in all five OCR configurations |
| #11: per-field accuracy printed for the tuning set | **done** (counts) | `docs/perception_eval_tuning.md`, `docs/perception_eval_tuning.json` |
| `read_nameplate(photo_path) -> PerceptionResult` | **done** | `src/amber_lens/perception/reader.py`; `read_observation(Observation)` too |
| `examples/perception_result_sample.json` from a real tuning photo | **done** | hf_038: 4 READ fields, all agree with the labels, 0 wrong READs |
| zero wrong READs on tuning | **not met as counted**: 5 left, see "Wrong READs" | 3 label-naming cases, 1 label gap, 1 multi-row table (hf_075, now flagged by the `multi_row_table` warning) |

## What was built and why

- `reader.py` applies the strict rule (T2-1 A) with every check you approved, in a fixed order. The
  result carries `vision_value`, `ocr_value`, `format_rule_passed` and, for every READ field, a
  `photo_crop` SourceRef with a box and a detail `field=...; label=...; located_by=...; pass=...`.
- Reason codes (T2-5 C) are returned through `run_nameplate(...)` from the same run, documented in the
  module docstring: `reasons`, `rules` (the exact check that stopped the field) and `located_by`.
- `catalog_number` is its own field (T2-4 B); the model's printed label is kept only if it is on a fixed
  list, so text from a plate cannot reach the source detail.
- Rules R1-R5 (T2-7 A) and power unit attachment (T2-8 A) each have a named test reproducing the case.
- OCR: Tesseract in 9 passes (A), RapidOCR (B), and label-anchored crops; the eval measures each engine
  and path separately and combined (`--ocr tesseract | rapidocr | both | tesseract+crops | both+crops`).
- The reader spike prompt is frozen byte-identical to T1, so `docs/reader_spike.md` reproduces from cache.

## Decisions (your answers) and what happened

| Id | Answer | Outcome |
| --- | --- | --- |
| T1-8 | qwen2.5vl:7b default; 3b dev only | `DEFAULT_VISION_MODEL`, `.env.example`; every number here uses 7b |
| T2-3 / T2-6 | A + C, then B if under 60% | C as specified was not buildable: model boxes 25-60% off and partly outside the image, ~4x slower. Built label-anchored crops instead (T2-6 B). A alone located 32%, so B (RapidOCR) was installed (21 s, under the 20 min box) |
| T2-4 | catalog_number field; match label on either identifier | model_number matched via model_number 15, via catalog_number 5 |
| T2-5 | reasons via a second function; schemas proposal as text | `run_nameplate`; proposal below |
| T2-7 | R1-R5, R2 at 8 px and 60% of the median line, manufacturer at least 3 letters | removed all 6 reader errors; R4 cost below |
| T2-8 | attach printed unit, number must sit next to it | power READ went from 3 to 9 (RapidOCR + Tesseract) |
| T2-9 | sample within ~45 min | delivered from hf_038 about 45 min after your answer; hf_02 is the DISPUTED example |
| T2-10 | default OCR = RapidOCR + Tesseract; crops an option, off | both samples regenerated with it, 0 wrong READs each; 19.5 s mean, 22.9 s max per photo |
| T2-11 | add R6 (rating table) | as a status rule it cost 11 correct key values (stricter version: 6), over the limit; shown to you |
| T2-12 | drop R6 as a status rule, keep it as the warning `multi_row_table` | `run_nameplate(...).warnings`; named test on hf_075; status unchanged |

## Results (35 tuning photos; 94 labelled key values; counts)

| OCR | key located | key READ correct | wrong READs (key) | s/photo |
| --- | --- | --- | --- | --- |
| Tesseract (A) | 30 | 17 | 3 (1) | 18.3 |
| Tesseract + crops | 34 | 19 | 3 (1) | 19.2 |
| RapidOCR | 61 | 42 | 5 (3) | 15.9 |
| RapidOCR + Tesseract | 66 | 41 | 5 (2) | 19.4 |
| RapidOCR + Tesseract + crops | 69 | 43 | 5 (2) | 34.9 |

Per path: crop_ocr gave 4 correct READs and 0 wrong; rapidocr 75 correct, 4 wrong; full_ocr (Tesseract)
5 correct, 1 wrong (RapidOCR + Tesseract run). Cost $0.00 everywhere.

**R4 alone** (RapidOCR + Tesseract): key values moved out of READ 5, of which 3 were correct (voltage 1/1,
current 4/2). Frequency, not a key field: 8 moved, 5 correct. Within your 5-value limit on key values; the
row-aware version is proposed as a follow-up for after Nov 25 because of the frequency cost. Not built.

T1 spike rerun from cache with the T2 locate rules: one count changes, qwen2.5vl:3b located arm wrong
READs 2 -> 1 (the hf_053 short number now needs its unit on the line). All other T1 counts are identical.

## Wrong READs (RapidOCR + Tesseract)

| photo | field | READ | label | assessment |
| --- | --- | --- | --- | --- |
| hf_04 | model_number | HLS447SR0608 | HHI150-12-447T | printed under MODEL; label has only the CAT. NO. (case 7) |
| hf_04 | manufacturer | Crown Triton | Hyundai (Crown Triton) | label naming (case 8) |
| hf_06 | manufacturer | Baldor Electric Co. | Baldor-Reliance | label naming (case 9) |
| darjja_train_14 | frequency | 60 | blank | plate prints HZ 60; label row blank because the photo is the CANT_MATCH case |
| hf_075 | voltage | 400 Δ / 690 Y | 400 Δ V | 4-row rating table; R4 misses it; it now carries the `multi_row_table` warning |

RapidOCR alone also READ `hf_072` current `0.62 A` (label blank; the plate prints `0.62 A`).
"Assessment" is an AI look at the photo, not a human check.

## Labels to re-check (for Vikas; tuning photos only)

1. `hf_04`: plate prints MODEL `HLS447SR0608` and CAT. NO. `HHI150-12-447T`; labels keep only the second. Add a catalog_number column?
2. `hf_04` manufacturer: printed `Crown Triton`, label `Hyundai (Crown Triton)`.
3. `hf_06` manufacturer: printed `Baldor Electric Co.`, label `Baldor-Reliance`.
4. `darjja_train_14` frequency: printed `HZ 60`, label blank.
5. `hf_072` rated_current: printed `0.62 A`, label blank.
6. `hf_075` voltage: printed rows 400 Δ / 690 Y / 460 Δ, label keeps `400 Δ V`.
7. `hf_038` / `hf_048` frequency: plate prints `50Hz` (190/380 V row) and `3/60CYCLE`; label keeps 60 Hz only.
8. Still open from T1: `hf_02` and `hf_04` glyphs (0/O, I/1), `hf_066`, `hf_053`, `darjja_train_10`, `hf_259`, `hf_06` identifier.

## Gaps and risks

- 5 wrong READs remain as counted; none is a clear reader misread, but a person has to confirm.
- The row-aware rule (a rating counts only on the same printed row as the other ratings) is the planned
  follow-up after Nov 25 for both R4's frequency cost and multi-row tables like hf_075.
- Latency is 19.5 s mean, 22.9 s max per photo with the 7B model plus OCR (35 s with crops).
- The `multi_row_table` warning fires on 16 of 35 photos; the detector is loose, so #16 should not
  send every warned verdict to a person without checking how often it fires.
- R4 holds back 5 correct frequency values; R5 blocks hf_02's model number because OCR never reads "MODEL".
- The labels are AI-read; all accuracy is agreement until the check sheet is done.
- RapidOCR adds about 17 packages through the `[ocr]` extra (onnxruntime, opencv-python-headless, numpy, ...).

## What a reviewer from another workstream should check

- `reader.py` `decide_field`: the order of checks and that no path sets a value without a `photo_crop` source.
- `locate.py`: the glued-label prefix rule can never absorb another number (tests
  `test_glued_prefix_may_be_a_folded_label_but_never_another_number`, `test_r1_fragment_darjja_train_11`).
- `examples/perception_result_sample.json` loads with `PerceptionResult.model_validate_json`.
- `pyproject.toml`: `[ocr]` gains `rapidocr>=3.4` and `onnxruntime>=1.20`.

## For other owners

- Shubhanshu (#15, #16): sample files in `examples/`; reasons and rules in the `_reasons.json` files.
- Koushik (#13) and Vikas: catalog_number note below.
- Vikas: re-check list above; switch `AMBER_DATA_DIR` when labels land on `main`.

## Draft texts (post on "post")

**schemas.py proposal for Shubhanshu (2 approvals needed; not applied)**

> Proposal: add one optional field to `ReadField`, additive, no existing code changes:
>
> ```python
> reason: Literal["format_fail", "readers_disagree", "not_located", "model_missing"] | None = Field(
>     default=None, description="Why a field is not READ; None when READ"
> )
> ```
>
> with a validator rule: `reason` must be None when `status == READ`, and set otherwise. Perception
> already produces these codes (today through `run_nameplate(...).reasons`); #16 can then read them
> straight from `PerceptionResult` and the UI can show them on the verdict card.

**#13 and Vikas: catalog_number**

> Perception now emits two identifiers, each read under its own printed label: `model_number` (MODEL,
> MOD, TYPE) and `catalog_number` (CAT. NO., CATALOG, ORD. NO.). Records and labels can carry both.
> Lookups should try `catalog_number` first, then `model_number`. The printed label is stored in the
> field's source detail (`label=CAT. NO.`). Example: hf_04 prints MODEL `HLS447SR0608` and CAT. NO.
> `HHI150-12-447T`; labels.csv currently holds only the catalog number.

**#11**

> Nameplate reader on all 35 tuning photos, qwen2.5vl:7b, $0.00 per photo. A field is READ only when the
> model's value passes its format rule and OCR finds the same characters printed on the photo (plus five
> stricter rules, each with a test). Counts vs AI-read labels (key values: model, voltage, current; 94):
> RapidOCR + Tesseract locates 66, READs 41 correctly, 5 wrong READs (all label-naming or label gaps, being
> re-checked). Sample PerceptionResult in `examples/`. Details in `docs/perception_eval_tuning.md`.

**#13 and #15 (replaces the T1 draft)**

> Perception emits `ReadField.name` = `model_number`, `catalog_number`, `voltage`, `rated_current`,
> `power`, `frequency`, `manufacturer`. Values are copied as printed with whitespace collapsed; a bare
> power number takes its printed unit label (`3` under `HP` -> `3 HP`). No other normalisation in
> perception; units, dash styles and decimal commas belong in the records normaliser. Please use the same
> keys in `Submittal.ratings`.

**WhatsApp to Shubhanshu**

> Hi Shubhanshu, the nameplate reader is pushed on `a/perception`. Two real tuning photos as examples in `examples/`:
> - `perception_result_sample.json` (hf_038): model `EPT0754`, voltage, power and manufacturer READ, 0 wrong READs
> - `perception_result_disputed_hf_02.json` (hf_02): some fields READ, some DISPUTED or UNREADABLE
>
> Load: `PerceptionResult.model_validate_json(Path("examples/perception_result_sample.json").read_text())`. Live: `read_nameplate(photo_path)` from `amber_lens.perception.reader`.
>
> Only READ fields have a value, and each READ has a `photo_crop` source with a bbox. DISPUTED means the model read something but OCR didn't confirm it; UNREADABLE means there's no usable value. Both have `value = None`, so treat them as missing data (not a GO).
>
> Why a field isn't READ is in the `_reasons.json` next to each sample: `model_missing`, `format_fail`, `not_located`, `readers_disagree`. Live: `run_nameplate(photo).reasons`. `tag_read_ok` is False here since no room tag is scanned yet.
>
> `warnings` in the same file: `multi_row_table` on voltage / current / frequency means the plate has a table with more than one rating row. The status doesn't change, but #16 can treat it as a signal that lowers confidence so the verdict goes to a person.
>
> Proposal for schemas.py (needs your OK + one more): an optional `reason` on ReadField, None when READ, so #16 can read it from PerceptionResult directly. Text is in `docs/task_reports/TASK_T2_nameplate_reader.md`. Model `qwen2.5vl:7b`, local, $0.00, ~20 s per photo.

## Exact run commands

```bash
.venv/Scripts/ruff check .
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m amber_lens.perception.reader ../amber-lens-data/data/photos/tuning/hf_038.jpg --out examples/perception_result_sample.json
.venv/Scripts/python -m amber_lens.perception.reader ../amber-lens-data/data/photos/tuning/hf_02.jpg --out examples/perception_result_disputed_hf_02.json
.venv/Scripts/python -m amber_lens.perception.evaluate --ocr both --json-out docs/perception_eval_tuning.json
```

Output: `ruff check .` -> `All checks passed!`; `pytest -q` -> `183 passed`.

## Files added or changed in T2

Added:
- `src/amber_lens/perception/reader.py`, `src/amber_lens/perception/evaluate.py`
- `tests/perception/test_perception_reader.py`, `tests/perception/test_perception_evaluate.py`
- `examples/perception_result_sample.json`, `examples/perception_result_sample_reasons.json`,
  `examples/perception_result_disputed_hf_02.json`, `examples/perception_result_disputed_hf_02_reasons.json`
- `docs/perception_eval_tuning.md`, `docs/perception_eval_tuning.json`, `docs/task_reports/TASK_T2_nameplate_reader.md`

Changed (T1 files, still uncommitted): `.env.example`, `pyproject.toml`, `src/amber_lens/perception/`
`README.md`, `fields.py`, `config.py`, `dataset.py`, `vision.py`, `ocr.py`, `locate.py`, `rules.py`,
`textfields.py`, `scoring.py`, `spike.py`, `check_sheet.py`; `tests/perception/` `test_perception_config.py`,
`test_perception_vision.py`, `test_perception_ocr.py`, `test_perception_locate.py`, `test_perception_rules.py`,
`test_perception_textfields.py`.

## Size

New: `reader.py` 301 lines, `evaluate.py` 185, `test_perception_reader.py` 246, `test_perception_evaluate.py` 75.
Added to T1 files: `ocr.py` +262 (now 392), `locate.py` +202 (260), `vision.py` +87 (270), `rules.py` +63 (161),
`fields.py` +18, `textfields.py` +15, `spike.py` +10, `scoring.py` +8, `config.py` +4, `check_sheet.py` +2,
`dataset.py` +2; tests +251 across 7 files.
Over the limits: `ocr.py` (392 > 300), `reader.py` (301), `decide_field` 42 lines, `evaluate.render` 42,
`OllamaVision.read` 50. These are the first targets of the cleanup pass after the handoff push (split crops
out of `ocr.py`, shorten the three functions), with behaviour unchanged.
Cut: R6 as a status rule (kept as a warning), path C with model boxes (not buildable), crops off by default.

## Proposed commits

T1 was never committed and T2 changed its files, so the T1 zip no longer matches the tree. Two commits in
order, each green on its own (to be verified before committing):

1. `a: reader spike, vision vs OCR on 10 tuning photos (#8)`: the T1 file list as it is now in the tree.
2. `a: nameplate reader with strict READ rule and tuning eval (#11)`: `reader.py`, `evaluate.py`, their
   two test files, `examples/` (4 files), `docs/perception_eval_tuning.md`, `docs/perception_eval_tuning.json`,
   `docs/task_reports/TASK_T2_nameplate_reader.md`.
