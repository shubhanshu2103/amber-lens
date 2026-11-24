# Roadmap

One straight run from Nov 21 to Dec 4. Each phase ends with something that actually runs, not a status update. If a phase slips we cut scope (bottom of this file), we don't move the submission date.

Issues are grouped under GitHub milestones with the same names.

## Phase 1: Foundations (Nov 21 - 23)

Get the data and the contracts sorted so nobody is blocked next week.

| # | Issue | Owner |
| --- | --- | --- |
| 1 | Email Kaya about the build window + rules | Vrushali |
| 2 | Book mentor office hours | Vrushali |
| 3 | Pull + filter public nameplate datasets | Vikas |
| 4 | Hand-verify ~40 photos + labels.csv | Vikas |
| 5 | Team photos + datasheets for 8-10 products | Vikas |
| 6 | Project Alpha records (CSV) | Koushik |
| 7 | Freeze schemas.py | Shubhanshu |
| 8 | Reader spike: vision vs OCR | Vrushali |
| 9 | Repo setup, branch protection | Shubhanshu |

**Done when:** verified photos + labels + records are committed and `schemas-v1` is tagged.

## Phase 2: Core loop (Nov 24 - 27)

One photo all the way through: capture -> read -> verdict -> Site PR -> approve -> write once -> verified.

| # | Issue | Owner |
| --- | --- | --- |
| 10 | Capture page | Vrushali |
| 11 | Nameplate reader | Vrushali |
| 12 | Flag instruction-like label text | Vrushali |
| 13 | Records in SQLite + lookups | Koushik |
| 14 | Sightings table | Koushik |
| 15 | Pre-install check | Shubhanshu |
| 16 | Confidence + review threshold | Shubhanshu |
| 17 | Ledger + Site PR state machine | Shubhanshu |
| 18 | Write once + verify + kill test | Shubhanshu |
| 19 | Eval harness skeleton | Vikas |
| 20 | Plant problems in records | Vikas |

**Done when:** the pre-install flow runs end to end on a tuning photo and survives a restart.

## Phase 3: Depth + integration (Nov 28 - Dec 1)

All three checks, Amber can call us over MCP, and we have honest numbers on the tuning set.

| # | Issue | Owner |
| --- | --- | --- |
| 21 | Substitution check | Shubhanshu |
| 22 | Read tickets + crate labels | Vrushali |
| 23 | Gate check | Shubhanshu |
| 24 | Self-check before claims / re-orders | Shubhanshu |
| 25 | Reopen on recurrence | Shubhanshu |
| 26 | Impact line from schedule float | Koushik |
| 27 | MCP server (6 tools) | Koushik |
| 28 | API for the review UI | Koushik |
| 29 | Review UI | Vrushali |
| 30 | Baseline model | Vikas |
| 31 | Tuning-set eval + failure review | Vikas, Shubhanshu |

**Done when:** all three checks work, MCP tools are callable from a real client, and the tuning eval table exists for us and the baseline.

## Phase 4: Proof + ship (Dec 2 - 4)

| # | Issue | Owner |
| --- | --- | --- |
| 32 | Freeze rules + single held-out run | Shubhanshu, Vikas |
| 33 | One-command setup + README | Koushik |
| 34 | Demo video | Vrushali |
| 35 | Pitch deck | Vrushali, Vikas |
| 36 | Devpost submission | Shubhanshu |

**Submit Dec 4.** Dec 5-6 is buffer only.

## If we fall behind, cut in this order

1. Reopen on recurrence (#25)
2. Impact line (#26), keep just the next action
3. Crate label reading, keep tickets only (#22)
4. Review UI polish, keep it functional (#29)

Never cut: substitution check, gate check, pre-install check, the Site PR loop, the MCP server, the held-out eval with baseline.

## Not building

Signal tracker, site-walk voice notes, graph DB / embeddings, confidence calibration from outcomes, native mobile app.
