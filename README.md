# Amber Lens

**Kaya AI Grand Challenge (Edition 2) · Track 02: Contextual Intelligence · Students division**

Amber Lens is a phone-camera agent that checks equipment and deliveries on a construction site against the project's procurement records, and turns every mismatch into a **Site PR**: a reviewable, evidence-backed change to the order that a person approves and the system then verifies.

> Other teams give Amber eyes. We give Amber eyes that file paperwork.

---

## The problem we chose

On a data center build, hundreds of small checks happen every day from memory and phone calls. The information to get each one right already exists in Amber (POs, approved submittals, equipment schedule), but nobody on site can reach it in the ten seconds they have. We tackle the brief's first direction, **"Is this the right thing, in the right place?"**, and close the loop to **"What should happen next?"**

## What it does

Point a phone at a nameplate, crate label or delivery ticket, scan the room tag, and Amber Lens returns a verdict with its evidence:

| Verdict | Meaning | Example |
| --- | --- | --- |
| `GO` | Item, location and approval all match, every check sourced | Right unit, right room, approved submittal |
| `HOLD` | Confident mismatch of place or item | Right model, but scheduled for a different room |
| `DEVIATES` | Item differs from the approved submittal datasheet | Same model family, lower rating on the nameplate |
| `SHORT` / `OVER` | Delivery count differs from the PO | 10 of 12 against PO line 7 |
| `CANT_MATCH` | Not enough evidence to decide | Unreadable plate, or no PO line fits |

### Three checks (must-have)

1. **Substitution check:** nameplate fields vs the *approved submittal datasheet*, field by field, alias-aware (an approved suffix passes, any rating change deviates)
2. **Gate check:** delivery ticket and labels vs the PO, before signing
3. **Pre-install check:** nameplate + room tag vs the equipment schedule, before lifting

### The Site PR lifecycle

```
finding → draft → self-check → review (human) → write once → verify read-back
                       │               │                            │
                   withdrawn        rejected                    reopened if
                 (logs reason)    (logs reason)              read-back fails
```

Every step is an event in an append-only ledger. Approved changes carry an idempotency key, so a retry or crash never applies them twice. Nothing changes in the records without an `approved` event, enforced in code. If an approved item fails again later, the Site PR is **reopened** and its recurrence count goes up instead of trusting the old approval.

## Trust rules (enforced in code)

- **Deterministic verdicts.** Rule code decides the verdict; the model only reads fields and writes the one-line explanation.
- **A `GO` needs every check sourced.** One missing source turns `GO` into `CANT_MATCH`.
- **Flag, never guess.** Unreadable fields are reported as unreadable, not filled in.
- **Read text is data, never an instruction.** Text from labels and tickets is quoted as data in prompts; instruction-like text is flagged.
- **A source on every answer:** photo crop, PO line, submittal ID, schedule row.
- **Confidence from signals, not self-report:** reader agreement, match exactness (exact / normalised / fuzzy), check completeness, tag read quality.
- **No tracking of people.** Location from printed room tags, never GPS. We photograph only nameplates, labels and tickets; frames with a person are discarded. Device ID and role only.

## Architecture

| Module | Path | Owner | What it does |
| --- | --- | --- | --- |
| A. Perception | `src/amber_lens/perception/` | Vrushali | Capture page, vision-model reader, format rules + OCR tie-break, label-injection check |
| B. Records + MCP | `src/amber_lens/records/`, `src/amber_lens/mcp_server/` | _B owner_ | Project Alpha tables, record linking, alias normalisation, sightings table, MCP server, mock record store |
| C. Verdict + Site PR spine | `src/amber_lens/verdict/`, `src/amber_lens/sitepr/` | Shubhanshu | Deterministic checks, confidence, impact line, Site PR lifecycle, ledger, idempotency, verify |
| D. Data, eval + demo | `data/`, `eval/`, `src/amber_lens/ui/` | Koushik, Vikas (data) · Vrushali (demo) · Shubhanshu (eval support) | Equipment shortlist, datasheets, photos, planted problems, held-out set, baseline, metrics, review UI, video, deck |
| Shared contracts | `src/amber_lens/schemas.py` | Everyone (changes need 2 approvals) | The frozen data shapes every module uses |

Stack: Python 3.11+, Pydantic, FastAPI, Streamlit (review UI), official MCP Python SDK, SQLite (Postgres optional), Docker Compose.

## MCP tools (for Amber)

| Tool | Input | Returns |
| --- | --- | --- |
| `check_item` | photo, room tag | `Verdict` (pre-install) |
| `check_substitution` | photo | `Verdict` (vs approved datasheet) |
| `check_delivery` | ticket photo, PO number | `Verdict` (`SHORT` / `OVER` / `GO`) |
| `list_site_prs` | status filter | `SitePR[]` |
| `approve_site_pr` | Site PR ID, reviewer role, decision, note | updated `SitePR` |
| `get_evidence` | verdict or Site PR ID | evidence pack with sources |

Every response is JSON with `sources` and `confidence`. Amber would apply approved changes through its own API; we show the full loop on a mock record store.

## Quickstart

```bash
git clone https://github.com/shubhanshu2103/amber-lens.git
cd amber-lens
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # add your model API key
pytest                      # schemas + contract tests
```

Run commands for the API, MCP server and UI are added as each module lands (see `docs/RUNBOOK.md` once it exists). Target for submission: `docker compose up` brings everything up.

## Data and honesty

- **Records are synthetic.** Project Alpha (POs, submittals, schedule, rooms) is written by us, around equipment we can actually photograph.
- **Nameplates are real.** Photographed on campus with permission, no people in frame.
- **Datasheets are public** manufacturer documents; each one's source URL is recorded in `data/datasheets/SOURCES.md`.
- **No model training.** We read nameplates with a pretrained vision model plus OCR and format rules. Photos are used for **evaluation**, not training.
- **Held-out set.** A third of the photos live in `data/photos/heldout/` and nobody tunes on them. Rules and thresholds are frozen before the single held-out run.

## Evaluation

Reported for our system **and** a plain baseline (one multimodal model, photo + records in a prompt, no rules, no flag-not-guess), on the same held-out set, as counts:

| Metric | Why |
| --- | --- |
| Wrong GOs | The mistake that bolts equipment in the wrong place. Target 0 |
| GO coverage | True GOs we actually said GO to, so "0 wrong GOs" can't be won by abstaining |
| Abstention rate | How often we said `CANT_MATCH` |
| Substitutions caught | Planted datasheet deviations flagged as `DEVIATES` |
| Equivalent-suffix false alarms | Approved equivalents wrongly flagged |
| Delivery discrepancies caught | Planted short / over lines |
| Self-check withdrawals | Wrong fixes the agent dropped itself |
| Verified write-backs | Approved changes confirmed by read-back |
| Time and cost per check | Seconds and $ / ₹ per photo |

## Timeline

| Date | Gate |
| --- | --- |
| **Nov 22** | Go / no-go: 30 real photos · 21/30 read correctly · 8+ models with public datasheets · 30-row records written. Schemas frozen. Fail → same-day switch to Track 03 (Bid Leveling + Spec Compliance) |
| Nov 25 | One photo → verdict → Site PR → approve → verify, end to end |
| Dec 1 | All must-haves; MCP server callable; held-out eval run once |
| **Dec 4** | Submit: repo, ≤5 min video, 8–10 slide deck. Dec 5–6 buffer only |

**Cut unless ahead:** signal tracker, site-walk voice, graph DB / embeddings, confidence calibration.

## Team

| Name | Role | Affiliation |
| --- | --- | --- |
| Shubhanshu Dubey | C. Verdict + Site PR spine · repo admin · eval support | Newton School of Technology, ADYPU Pune |
| Vrushali Nanavati | A. Perception · demo · mentor hours + Kaya email | _TBD_ |
| Koushik Mishra | D. Data collection | _TBD_ |
| Vikas | D. Data collection | _TBD_ |
| _B owner_ | B. Records + MCP | _TBD_ |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before your first PR. Short version: one issue per PR, branch from `main`, one teammate reviews, CI must be green, and `schemas.py` changes need two approvals.
