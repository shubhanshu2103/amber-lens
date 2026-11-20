# Contributing to Amber Lens

## Workflow

1. **Pick an issue** assigned to you. One issue = one PR, finishable in 1–2 days.
2. **Branch from `main`:** `a/reader-rule`, `b/mcp-server`, `c/verdict-engine`, `d/heldout-split` (workstream letter + short name).
3. **Commit small,** with messages like `c: add GO-needs-sources check`.
4. **Open a PR** using the template, link the issue (`Closes #12`), request one reviewer from another workstream.
5. **Merge** only when CI is green and one approval is in. Squash-merge.

`main` is protected: no direct pushes.

## Rules that are not negotiable

- **`src/amber_lens/schemas.py` is the contract.** Changes need 2 approvals and a note in the team chat, because they break other people's code.
- **Never open `data/photos/heldout/`** while building or tuning. It is run once, after rules are frozen.
- **Flag, never guess.** If code can't decide, it returns `CANT_MATCH` or `UNREADABLE`, never a best guess.
- **Every output has `sources` and `confidence`.**
- **No secrets in git.** API keys go in `.env` (copy from `.env.example`).
- **No people in photos.** Only nameplates, labels, tickets. Discard any frame with a person in it.

## Syncs

- 15-minute sync every two days; each person says: done, next, blocked.
- Full end-to-end run at each sync from Nov 25 onward.
- If a gate slips, we cut scope (see README "Cut unless ahead"), never the submission date.

## Labels

`A-perception` · `B-records-mcp` · `C-verdict-sitepr` · `D-data-eval-demo` · `gate:nov22` · `gate:nov25` · `gate:dec1` · `gate:dec4` · `blocked` · `bug`
