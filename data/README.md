# Data

| Folder | What goes here | Owner |
| --- | --- | --- |
| `photos/tuning/` | Photos we build and debug on | D (Koushik, Vikas) |
| `photos/heldout/` | At least a third of all photos. **Nobody opens these while building.** Run once, after rules freeze | D |
| `datasheets/` | Public manufacturer datasheets (PDF) for each photographed model | D |
| `records/` | Project Alpha tables as CSV: `po_lines.csv`, `submittals.csv`, `schedule.csv`, `rooms.csv`, `deliveries.csv` | B |
| `labels.csv` | Ground truth per photo: `photo_id, model_number, true_verdict, planted_problem, notes` | D |

## Photo rules
- Nameplates, crate labels, delivery tickets only. **No people in frame**; discard and retake if anyone appears.
- Name files `<model-slug>_<nn>_<condition>.jpg`, e.g. `daikin-ftkf50_03_glare.jpg`.
- Vary angle, distance, glare and wear on purpose.
- Split tuning / held-out **by model**, not by photo, so the held-out set has models the system never saw while tuning.

## Planted problems (record edits, not equipment edits)
Wrong room · changed rating vs datasheet · approved equivalent suffix (must pass) · unapproved submittal · short / over delivery · "missing" item that has a sighting · unreadable plate · no PO line · label with an injection line.
