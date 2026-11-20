# Evaluation

`eval/` holds the harness that scores our system and the baseline on the same photos.

- `run_eval.py` (to build): runs every photo in a split through the pipeline, compares with `data/labels.csv`, prints counts.
- `baseline.py` (to build): one multimodal model, photo + records in a prompt, no rules, no flag-not-guess.

Output is a table of counts (not just percentages): wrong GOs, GO coverage, abstention rate, substitutions caught, suffix false alarms, delivery discrepancies caught, self-check withdrawals, verified write-backs, time and cost per check.

The held-out split is run **once**, after rules and thresholds are frozen and committed.
