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
`photo_id, split, source, license, equipment_type, manufacturer, model_number, voltage, hp_or_kw, amps, readable, true_verdict, planted_problem, notes`

See the header of `labels.csv` for the exact order; `true_verdict` and `planted_problem` are filled in #20 once records exist.

## Rules
- Public dataset labels are auto-generated and wrong in places. Never copy them in without checking the photo.
- Split tuning / held-out **by model**, not by photo.
- Rename files as `<brand-model>_<nn>.jpg`.

## Planted problems (record edits, not photo edits)
Wrong room · changed rating in the approved submittal · approved equivalent suffix (must pass) · unapproved submittal · short / over delivery · "missing" item that has a sighting · unreadable plate · no PO line · label with an injection line.
