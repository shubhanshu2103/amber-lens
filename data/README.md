# Data

| Path | What goes here | Owner |
| --- | --- | --- |
| `photos/tuning/` | Photos we build and debug on (~2/3 of models) | Vikas |
| `photos/heldout/` | ~1/3 of models. **Nobody opens these while building.** Run once, after rules freeze | Vikas |
| `labels.csv` | Hand-verified ground truth for every photo | Vikas |
| `SOURCES.md` | Every dataset and datasheet we used, with link and license | Vikas |
| `datasheets/` | Official datasheet PDFs, only for the products where we found one | Vikas |
| `records/` | Project Alpha tables as CSV: `po_lines.csv`, `submittals.csv`, `schedule.csv`, `rooms.csv`, `deliveries.csv` | Koushik |

## What a usable photo needs
- equipment you'd find on a building or data center site (motors, pumps, fans, HVAC, compressors, transformers, UPS, inverters, generators, breakers, panels)
- a readable model number and at least 2 ratings (volts, amps, HP/kW...)
- no people in the frame

Keep 3-4 blurry or damaged plates on purpose; they are our `CANT_MATCH` cases.

## labels.csv columns
`photo_id, source, license, manufacturer, model_number, voltage, hp_or_kw, amps, true_verdict, planted_problem, notes`

labels.csv also carries the columns used by `scripts/data/`: `image_id` (same as `photo_id`), `file_name`, `source_url`, `model_group` (model number uppercased, spaces removed; the split key), `equipment_type`, `rating_1` / `rating_2` (two ratings exactly as printed), `frequency`, `power` (same as `hp_or_kw`), `readable`, quality columns (`quality, angle, lighting, glare, obscured, small_text`), `split`, `verified_by` (`claude-code-vision`) and `human_checked` (empty until a person checks the row). `voltage` / `amps` are split out of the ratings; `amps` is empty when the plate prints no current.

`true_verdict` is `CANT_MATCH` for unreadable plates and blank otherwise, because verdicts depend on the records and planted problems (#20). `metadata/photo_review.csv` lists every photo looked at, including rejects and why.

## Rules
- Public dataset labels are auto-generated and wrong in places. Never copy them in without checking the photo.
- Split tuning / held-out **by model**, not by photo.
- Public-dataset photos keep their source name with a prefix (`hf_<original>`, `darjja_<split>_<nn>`) so they trace back to the source row; own photos use `<brand-model>_<nn>.jpg`.

## Planted problems (record edits, not photo edits)
Wrong room · changed rating in the approved submittal · approved equivalent suffix (must pass) · unapproved submittal · short / over delivery · "missing" item that has a sighting · unreadable plate · no PO line · label with an injection line.
