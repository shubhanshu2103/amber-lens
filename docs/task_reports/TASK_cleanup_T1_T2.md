# Cleanup pass on the T1 / T2 code (standing rule: short and direct)

Done after the handoff push (`9cbd14f` on `origin/a/perception`). Behaviour unchanged.

## Evidence that behaviour did not change

- 35-photo eval (`--ocr both`): every field of every photo and every score is identical before and after
  (compared as JSON, latency ignored). The only text difference is one summary line split into two.
- Reader spike rerun from cache: key-field counts identical.
- `ruff check .` clean; `pytest -q`: 182 passed (184 before; the dropped tests covered removed checks).

## What changed

- `ocr.py`: the label-anchored crop path moved to its own `crops.py`; the OCR runner table moved to
  `evaluate.py`, its only user. Removed checks for things that cannot happen (empty box list, zero-width
  image, non-256-bin histogram, unknown fixed variant, combining nothing) and the one-use `pass_lines`.
  `group_lines` uses an ordered dict; one `make_line` helper replaces three copies of the line builder.
- `reader.py`: `decide_field` 42 -> 31 lines. The checks after locating moved into `_check_located` in the
  same order, so one `_stop` call replaces seven. Docstring tightened, same rule list.
- `vision.py`: `OllamaVision.read` 50 -> 13 lines plus `_generate`; same cache entry shape, so existing
  cache files still hit.
- `evaluate.py`: `render` split; path and rule lines in `_paths_and_rules`.
- `spike.py`: dropped a check on an empty list that cannot happen.
- Tests: `test_perception_ocr.py` rewritten with parametrize (188 -> 118 lines); crop test in its own file.

## Lines before -> after

| file | before | after |
| --- | --- | --- |
| src/amber_lens/perception/ocr.py | 392 | 250 |
| src/amber_lens/perception/crops.py | 0 | 95 |
| src/amber_lens/perception/reader.py | 301 | 286 |
| src/amber_lens/perception/vision.py | 270 | 253 |
| src/amber_lens/perception/evaluate.py | 185 | 201 |
| src/amber_lens/perception/spike.py | 237 | 235 |
| src/amber_lens/perception/check_sheet.py | 167 | 167 |
| tests/perception/test_perception_ocr.py | 188 | 118 |
| tests/perception/test_perception_crops.py | 0 | 17 |
| tests/perception/test_perception_reader.py | 246 | 247 |
| tests/perception/test_perception_spike.py | 87 | 83 |
| all perception src + tests | 3629 | 3508 |

No module is over 300 lines and no function over 40. `check_sheet.py` is unchanged: most of it is the
page's HTML and CSS, and its logic has no duplication to remove. `evaluate.py` grew by the runner table it
took over from `ocr.py`.

## Files changed

`src/amber_lens/perception/ocr.py`, `crops.py` (new), `reader.py`, `vision.py`, `evaluate.py`, `spike.py`,
`README.md`; `tests/perception/test_perception_ocr.py`, `test_perception_crops.py` (new),
`test_perception_reader.py`, `test_perception_spike.py`; this report.

## Proposed commit

`a: cleanup perception code, no behaviour change (#11)`; stage the files above.
