import argparse
import sys
from pathlib import Path

import pandas as pd

REQUIRED = ["image_id", "file_name", "source", "source_url", "license", "model_group", "manufacturer",
            "model_number", "rating_1", "rating_2", "readable", "true_verdict", "split", "verified_by"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="data/labels.csv")
    ap.add_argument("--photos", default="data/photos")
    ap.add_argument("--min-verified", type=int, default=40)
    args = ap.parse_args()

    df = pd.read_csv(args.labels, dtype=str).fillna("")
    errors = []

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        errors.append(f"missing columns: {missing}")
        df = df.reindex(columns=list(df.columns) + missing, fill_value="")

    readable = df[df["readable"] == "yes"]
    for col in ("model_number", "rating_1", "rating_2"):
        bad = readable[readable[col].str.strip() == ""]
        if len(bad):
            errors.append(f"{len(bad)} readable rows have empty {col}: {list(bad['image_id'])[:5]}")

    bad_cm = df[(df["readable"] == "no") & (df["true_verdict"] != "CANT_MATCH")]
    if len(bad_cm):
        errors.append(f"unreadable rows must be CANT_MATCH: {list(bad_cm['image_id'])[:5]}")

    both = df.groupby("model_group")["split"].nunique()
    leaked = list(both[both > 1].index)
    if leaked:
        errors.append(f"model groups in both splits: {leaked}")

    if df["image_id"].duplicated().any():
        errors.append("duplicate image_id values")

    missing_photos = [f"{r['split']}/{r['file_name']}" for _, r in df.iterrows()
                      if not (Path(args.photos) / r["split"] / r["file_name"]).exists()]
    if missing_photos:
        errors.append(f"{len(missing_photos)} photos not found, e.g. {missing_photos[:3]}")

    if len(readable) < args.min_verified:
        errors.append(f"only {len(readable)} readable verified photos, need {args.min_verified}")

    print(f"rows {len(df)} | readable {len(readable)} | CANT_MATCH {int((df['true_verdict'] == 'CANT_MATCH').sum())} "
          f"| models {df['model_group'].nunique()} | tuning {int((df['split'] == 'tuning').sum())} "
          f"| heldout {int((df['split'] == 'heldout').sum())}")
    if errors:
        print("\n".join(f"FAIL: {e}" for e in errors))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
