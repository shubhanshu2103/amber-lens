# Task T5: read delivery tickets and crate labels (#22)

Owner: A Perception (Vrushali). Not committed yet.

## "Done when" (#22)

| Item | Status | Evidence |
| --- | --- | --- |
| works on the ticket photos in tuning | **reinterpreted, per T5-1 C**: no ticket photos exist in tuning. Works on the rendered synthetic ticket and crate label (part A); real phone photos of printed synthetic documents are Vikas's part B (request below) | real-model run: ticket 8 of 8 fields READ and correct; crate label 4 of 4 READ and correct, instruction line flagged |
| no guessing | **done** | a cell is READ only from one exact OCR word in its column and row; otherwise DISPUTED with value None |

## What was built and why

- `documents.py` (158 lines): `read_crate_label`, `read_delivery_ticket` and `read_observation` (moved
  here from `reader.py`; it now dispatches nameplate / crate_label / delivery_ticket, and refuses packing slips).
- Crate label: the nameplate rule, with the label anchor (R5) applied to all four fields.
- Ticket header (po_number, delivery_ticket_id): the nameplate rule with the label anchor.
- Ticket cells (your T5-2 A plus additions): a cell is READ only from exactly one OCR word that equals the
  vision value **exactly** (no glyph folding), sits under its column header (Model, Qty, Line) and, for qty and
  po_line, on the same printed row as the line's model number (vertical overlap at least 50% of the shorter box).
  No match: `not_located` (`cell_not_found`); two or more: `readers_disagree` (`ambiguous_cell`). A line whose
  model number is not READ gets `line_model_not_read` for its other cells. Flagged lines and fragments still stop a cell.
- Warning `line_count_mismatch` (key `lines`) when the model's line count differs from the model numbers OCR
  finds under the Model column. Every line is still decided by its own row.
- `reader.py` now has one shared core, `read_document` (photo checks, vision call, OCR evidence, flagged lines,
  result), used by nameplates, crate labels and tickets; `decide_field` takes the set of label-anchored fields.
- Prompts `crate-label-v1` (labelled) and `delivery-ticket-v1` (header + `lines` array, explicit JSON schema),
  no digits in either.

## Three locate fixes found by the crate label (each tightens or clarifies; nameplate eval unchanged)

1. A label glued to a value must end in a separator (`.`, `:`, `#`): `Qty:1`, `AMP.7.8/3.9`. Before, the title
   word `LABEL` passed as "labe" + "l" (folded to 1) and hid the real `Qty:1`.
2. A slash glued to the end of a word (`ALPHA-0412/`) is not part of the value.
3. R1 (fragment): that trailing slash continues the value only when a digit follows (`230/` `460` stays a
   fragment); `ALPHA-0412/` `Line` is a separator. A bug I introduced while editing (an empty next word counted
   as a joiner) was caught by the real run and fixed before any result was kept.

## Results

| document (synthetic, rendered) | fields READ and correct | not READ | warnings | latency |
| --- | --- | --- | --- | --- |
| delivery ticket DT-88213 | 8 of 8 (PO, ticket ID, 2 lines x model / qty / po_line) | 0 | none | 14.1 s |
| crate label SRT (with the instruction line) | 4 of 4 (model SRTG10KXLI, qty 1, PO ALPHA-0412, line 2) | 0 | none | 12.4 s |

The crate label's NOTE TO RECEIVER line comes back as `free_text_1`: DISPUTED, value None, injection_flag.

## Nameplate eval check (35 tuning photos, after the locate fixes)

Scores identical: 41 key values READ and correct, 5 wrong READs (2 key). **No field changed status or value.**
Three DISPUTED fields stop at a different check:

| photo / field | before | after |
| --- | --- | --- |
| darjja_train_01 catalog_number `ITF312500` | located as `CODEITF312500` (glued prefix without separator), then `label_anchor_missing` | `not_found` |
| hf_047 model_number `A36-8063-4076` | located as `SECA36-8063-4076`, then `label_anchor_missing` | `not_found` |
| hf_092 rated_current `12.3 / 6.15` | `not_found` | found (trailing-slash fix), then `multi_rating` (R4) |

Reported metrics that moved: key values located 66 -> 67 (70% -> 71%); R4 on rated_current 4 -> 5 values held
back (3 correct; key total 4 correct, within your limit of 5). `docs/perception_eval_tuning.md` and `.json` are
updated to this run, with a change-log entry.

## Tests

CI (stand-ins, 11 new): every cell READ; **the probe case** (line 1 `po_line` "1" found only in the title row is
not READ); a folded cell `1O` for `10` not READ; an ambiguous cell not READ; row overlap 8 px of 20 READ, 12 px
shift not READ; a line without a READ model has no READ cells and raises `line_count_mismatch`; the crate label
reads its 4 fields and flags the instruction line; the glued-label and trailing-slash rules; dispatch by kind.
Local (`local_model`, 2 new, real qwen2.5vl:7b): SRT crate label and the ticket, both passed.
Totals: `ruff check .` clean, `pytest -q` 231 passed; local 6 passed (2 documents + 4 injection variants).

## Draft: photo-shoot request for Vikas (#5, part B of T5-1)

> Hi Vikas, for #22 we need real phone photos of printed synthetic documents. Could you add these to the #5
> shoot? Print `data/delivery_documents/SYN_DELIVERY_TICKET_DT-88213.md` (as a table) and
> `SYN_CRATE_LABEL_SRT.md`, and photograph each 3 times: straight on, tilted about 15 degrees, and in dim light.
> No people or hands in the frame. Please store them outside `data/photos/` (for example
> `data/document_photos/`), name them `synthetic-document_real-photo_<doc>_<nn>.jpg`, and note in SOURCES.md
> that the documents are synthetic and the photos are real. Keep the "NOTE TO RECEIVER" line on the crate label:
> it is our injection test.

## Draft: #23 field names (post on "post")

> Perception now reads delivery tickets and crate labels (#22). Field names in `PerceptionResult.fields`:
> ticket: `po_number`, `delivery_ticket_id`, and per table row n (1-based, in printed order)
> `line[n].model_number`, `line[n].qty`, `line[n].po_line` (the value in the ticket's Line column);
> crate label: `model_number`, `qty`, `po_number`, `po_line`. Values are as printed; qty and po_line are
> integers as strings. A cell is READ only when OCR finds exactly that value in its column and on its line's
> row; otherwise it is DISPUTED with value None, so the gate check should treat a missing qty as CANT_MATCH,
> never as 0. `run_nameplate`-style traces come from `read_delivery_ticket(...)` / `read_crate_label(...)`,
> including the warning `line_count_mismatch` when the model and OCR count different lines.

## Gaps and risks

- Only rendered synthetic documents so far; real photos (Vikas) will show more OCR noise, tilt and glare.
- Right-aligned or multi-line cells and model numbers split by OCR into two words are not READ (DISPUTED).
- Packing slips are not read yet (refused with a clear error).
- The ticket prompt asks the model to copy table text; cells are still decided only by the OCR row/column rule,
  and flagged lines block cells, so ticket text cannot steer a READ value.

## Files added or changed

Added: `src/amber_lens/perception/documents.py`, `tests/perception/test_perception_documents.py`,
`tests/perception/test_perception_documents_local.py`, `tests/fixtures/perception/synthetic_ticket_dt_88213.png`,
this report.
Changed: `src/amber_lens/perception/reader.py`, `vision.py`, `rules.py`, `locate.py`, `injection.py`, `crops.py`,
`README.md`; `docs/perception_eval_tuning.md`, `docs/perception_eval_tuning.json` (T5 run);
`tests/fixtures/perception/make_synthetic_injection_labels.py` (draws the ticket too; the four label
images are byte-identical); `tests/perception/test_perception_reader.py`.

## Size

documents.py 158 lines (new); reader.py 296 (-1: shared `read_document` replaced the nameplate-only pipeline),
locate.py 272 (+33), vision.py 291 (+38: two prompts), rules.py +8, injection.py -6, crops.py -9; tests +147.
No function over 40 lines. Cut: packing slips, multi-word cells, a separate document pipeline (reuses the
nameplate core).

## Proposed commit

`a: read delivery tickets and crate labels with row and column checks (#22)`; stage the files above.
