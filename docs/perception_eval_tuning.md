# Nameplate reader on the tuning set (#11)

All 35 tuning photos, prompt `nameplate-labelled-v1`, temperature 0, fixed seed. The default vision model is
`qwen/qwen3.8-27b` on Groq; the rule was built and first measured with a local `qwen2.5vl:7b` (RTX 4050 laptop,
$0.00 per photo), and the tables below the next section are from that local run. Both models are compared
under "Model-agnostic: the same rule on two models".

**Truth is not yet human-verified.** `labels.csv` was read off the photos by an AI model and
`human_checked` is empty, so "correct" means agreement with AI-read labels. Labels come from the
read-only worktree of `d/dataset-hf-40` (`AMBER_DATA_DIR=../amber-lens-data/data`); when the final
`labels.csv` lands on `main`, switch `AMBER_DATA_DIR` to `./data` and rerun.

## The rule

A field is READ only if all checks pass (full list in `src/amber_lens/perception/reader.py`):
the vision model gave a value; it passes its format rule, and a rating holds only its own unit words
(R3); OCR finds it printed on the photo in a box at least 8 px and 60% of the median line high (R2); the
match is not a fragment of a longer token (R1); OCR read the same characters; an attached power unit sits
right next to the number (T2-8); an identifier has its own printed label beside or above it (R5);
OCR's own reading under the field's label does not differ; and OCR does not see two or more different
voltage, current or frequency values on the plate (R4). Otherwise the value is None, the status is
UNREADABLE or DISPUTED, and the reason is one of `model_missing`, `format_fail`, `not_located`,
`readers_disagree`.

## Model-agnostic: the same rule on two models

The same strict rule and the same local OCR, measured 2026-11-25 (key values: model number, voltage, current).

| photos | vision model | key values READ and correct | wrong READs (key) | located | s/check total (vision, OCR in parallel) | tokens / check | cost / check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 35 | **qwen/qwen3.8-27b, Groq (default)** | 39 of 94 | 4 (3) | 65 of 94 | **5.3** (1.1, 5.3), max 8.3 | 2,155 | $0.0025 list, $0 free tier |
| 35 | qwen2.5vl:7b, local (offline mode) | 41 of 94 | 5 (2) | 67 of 94 | 15.8 (15.8, 7.2), max 36.7 | 1,576 | $0 |
| 10 (spike) | qwen/qwen3.8-27b, Groq | 11 of 26 | 1 (1) | 18 of 26 | 4.9 (1.2, 4.9) | 2,202 | $0.0025 list |
| 10 (spike) | qwen2.5vl:7b, local | 12 of 26 | 3 (1) | 19 of 26 | 16.6 (16.6, 7.8) | 1,580 | $0 |

The model choice barely moves wrong READs because OCR must confirm every value. Groq's 3 key wrong READs:
hf_04 model_number (MODEL vs CAT. NO.) and hf_075 voltage (multi-row table) are also wrong with the local model;
darjja_train_14 current is printed but unlabelled (label gap). Local's 2 are the same hf_04 and hf_075.
Groq's one clear misread, darjja_train_12 power `79.0 HP`, is blocked by the power-unit rule (named test).

## Engines and paths (key values = model number via either identifier, voltage, rated current; 94 labelled)

| OCR used to locate | key values located | key values READ and correct | wrong READs, all fields (key) | s / photo mean (max) |
| --- | --- | --- | --- | --- |
| Tesseract, 9 passes (path A) | 30 (32%) | 17 | 3 (1) | 18.3 (22.4) |
| Tesseract + label-anchored crops (A + crops) | 34 (36%) | 19 | 3 (1) | 19.2 (22.5) |
| RapidOCR | 61 (65%) | 42 | 5 (3) | 15.9 (19.3) |
| **RapidOCR + Tesseract (default)** | **67 (71%)** | **41** | **5 (2)** | **19.5 (22.9)** |
| RapidOCR + Tesseract + crops | 69 (73%) | 43 | 5 (2) | 34.9 (55.3) |

Located boxes by path in the RapidOCR + Tesseract run: rapidocr 110, full_ocr (Tesseract) 11. Correct READs
by path: rapidocr 75, full_ocr 5. With crops added: crop_ocr located 5 more boxes, all 4 crop READs were
correct and the crop path produced **0 wrong READs**.

The model-box version of path C was not built: on hf_02 and hf_04 the boxes qwen2.5vl:7b returned were
25-60% away from the text and partly outside the image, and asking for boxes made each read about 4x slower.
The label-anchored crops above replace it.

**Default: RapidOCR + Tesseract** (decision T2-10). Crops stay available as `--ocr "both+crops"`, off by
default. Measured with the local model before vision and OCR ran in parallel: 19.5 s mean, 22.9 s max
per photo, $0.00. Current per-check times are in the two-model table above.

## R6, the rating-table rule: measured, then kept as a warning only

Applied as a status rule, R6 (a row of unit headers V / Hz / A / kW / HP with rows of values under it)
removed the hf_075 wrong READ but fired on 11 photos and moved 12 key values out of READ, 11 of them
correct (plus 6 correct frequencies). A stricter version (3+ headers, 2+ aligned value rows) still cost 6
correct key values. Both are over the 5-value limit, so R6 now only adds the warning `multi_row_table` to
voltage, current and frequency (`run_nameplate(...).warnings`); status comes from the other rules alone.
The row-aware rule is the planned follow-up after Nov 25.

The warning fires on 16 of 35 tuning photos (darjja_train_10, darjja_train_14, hf_022, hf_025, hf_047,
hf_053, hf_069, hf_072, hf_075, hf_09, hf_090, hf_092, hf_174, hf_175, hf_286, hf_306). The detector is
loose; if #16 lowers confidence on every warning, about half of the verdicts go to a person.

## Per field, RapidOCR + Tesseract

| field | correct | wrong | extra | missed | abstained ok |
| --- | --- | --- | --- | --- | --- |
| model_number (either identifier) | 20 | 1 | 0 | 11 | 3 |
| voltage | 13 | 1 | 0 | 18 | 3 |
| rated_current | 8 | 0 | 0 | 22 | 5 |
| power | 9 | 0 | 0 | 19 | 7 |
| frequency | 10 | 0 | 1 | 22 | 2 |
| manufacturer | 20 | 2 | 0 | 9 | 4 |

model_number matched the label through `model_number` 15 times and through `catalog_number` 5 times.

| field | READ | model_missing | format_fail | not_located | readers_disagree |
| --- | --- | --- | --- | --- | --- |
| model_number | 17 | 0 | 1 | 16 | 1 |
| catalog_number | 6 | 2 | 1 | 26 | 0 |
| voltage | 14 | 0 | 4 | 9 | 8 |
| rated_current | 8 | 0 | 2 | 9 | 16 |
| power | 9 | 1 | 12 | 13 | 0 |
| frequency | 11 | 0 | 1 | 15 | 8 |
| manufacturer | 22 | 1 | 2 | 9 | 1 |

## R4 (multi-rating plate) cost, RapidOCR + Tesseract

| field | moved out of READ by R4 alone | of which the vision value was correct |
| --- | --- | --- |
| voltage (key) | 1 | 1 |
| rated_current (key) | 5 | 3 |
| frequency | 8 | 5 |

Key values: R4 moves 6 out of READ, 4 of them correct (within the 5-value limit). Counting frequency it
holds back 8 correct values, so the row-aware version is proposed as a follow-up after the Nov 25 handoff.

## Every wrong READ (RapidOCR + Tesseract)

| photo | field | READ | label | what the photo shows (AI look, not a human check) |
| --- | --- | --- | --- | --- |
| hf_04 | model_number | HLS447SR0608 | HHI150-12-447T | printed under MODEL; the label keeps only the CAT. NO., which was not located |
| hf_04 | manufacturer | Crown Triton | Hyundai (Crown Triton) | printed as Crown Triton; the label names the parent brand |
| hf_06 | manufacturer | Baldor Electric Co. | Baldor-Reliance | printed as Baldor Electric Co.; the label uses the current brand name |
| darjja_train_14 | frequency | 60 | (blank) | the plate prints HZ 60; the label row is blank because the model number is unreadable |
| hf_075 | voltage | 400 Δ / 690 Y | 400 Δ V | a 4-row rating table (400 Δ / 690 Y at 50 Hz, 460 Δ at 60 Hz); R4 did not detect the table |

The six reader errors found earlier tonight (`13ACD` fragment, `ee` logo, `1.82Y`, `50` on two 60 Hz
plates, `03D 87250` without a catalog label) are all removed by R1-R5 and each has a named test.

## Change log

- T5 (#22) locate fixes (glued labels need a separator; a glued trailing slash is not part of the value):
  no status or value changed on any tuning field. Located key values 66 -> 67 (hf_092 current is now found,
  then held back by R4); R4 on current 4 -> 5 values (3 correct). Two fields stop at not_located instead of
  label_anchor_missing. Counts above are from this run.

## Reproduce

```bash
python -m amber_lens.perception.evaluate --ocr both --json-out docs/perception_eval_tuning.json
python -m amber_lens.perception.evaluate --ocr tesseract
python -m amber_lens.perception.evaluate --ocr rapidocr
python -m amber_lens.perception.evaluate --ocr "tesseract+crops"
python -m amber_lens.perception.evaluate --ocr "both+crops"
```

Vision answers are cached by image hash, model and prompt version, so reruns repeat only OCR and the
counts are identical; latency is the time measured on the first vision call plus the live OCR time.
