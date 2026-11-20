# Starter issues (Nov 20–25)

Copy each into GitHub as an issue with the labels shown.

## Before the Nov 22 go / no-go
| # | Title | Labels | Owner |
| --- | --- | --- | --- |
| 1 | Email Kaya: is code written before Nov 30 allowed? Read Rules tab | `gate:nov22` | Vrushali |
| 2 | Book mentor office hours; ask which site check costs most when missed | `gate:nov22` | Vrushali |
| 3 | Get permission to photograph campus electrical / plant rooms | `D-data-eval-demo` `gate:nov22` | Koushik / Vikas |
| 4 | Shortlist 15–20 equipment models; keep 8–10 with public datasheets, fill `SOURCES.md` | `D-data-eval-demo` `gate:nov22` | Koushik / Vikas |
| 5 | Shoot 30+ photos; split tuning / held-out by model; write `labels.csv` | `D-data-eval-demo` `gate:nov22` | Koushik / Vikas |
| 6 | Write Project Alpha CSVs (~30 PO lines) around the chosen models | `B-records-mcp` `gate:nov22` | B owner |
| 7 | Vision model vs OCR vs reader rule on tuning photos: per-field accuracy | `A-perception` `gate:nov22` | Vrushali |
| 8 | Freeze `schemas.py` (review + 2 approvals) | `C-verdict-sitepr` `gate:nov22` | Shubhanshu |

## Toward the Nov 25 end-to-end gate
| # | Title | Labels | Owner |
| --- | --- | --- | --- |
| 9 | Reader: photo → `PerceptionResult` with crops; label-injection flag | `A-perception` `gate:nov25` | Vrushali |
| 10 | Capture page: photo + room QR tag → `Observation` | `A-perception` `gate:nov25` | Vrushali |
| 11 | Load CSVs into SQLite; lookup by model number with suffix normalisation | `B-records-mcp` `gate:nov25` | B owner |
| 12 | Sightings table + query "where was model X seen last 7 days" | `B-records-mcp` `gate:nov25` | B owner |
| 13 | Verdict engine: pre-install check (model, room, submittal approved) | `C-verdict-sitepr` `gate:nov25` | Shubhanshu |
| 14 | Confidence from signals (agreement, match type, completeness, tag) | `C-verdict-sitepr` `gate:nov25` | Shubhanshu |
| 15 | Ledger + Site PR state machine + idempotent write + read-back verify | `C-verdict-sitepr` `gate:nov25` | Shubhanshu |
| 16 | Kill-between-approve-and-write test: change applied exactly once | `C-verdict-sitepr` `gate:nov25` | Shubhanshu |
| 17 | Eval harness skeleton: run split, compare with `labels.csv`, print counts | `D-data-eval-demo` `gate:nov25` | Koushik / Vikas + Shubhanshu |
