import argparse
import hashlib
import shutil
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="data/labels.csv")
    ap.add_argument("--photos", default="data/photos")
    ap.add_argument("--heldout-share", type=float, default=1 / 3)
    args = ap.parse_args()

    df = pd.read_csv(args.labels, dtype=str).fillna("")
    groups = df.groupby("model_group").size()

    # stable pseudo-random order of model groups, so reruns give the same split
    order = sorted(groups.index, key=lambda g: hashlib.sha1(g.encode()).hexdigest())
    target = round(len(df) * args.heldout_share)
    heldout, count = set(), 0
    for g in order:
        if count >= target:
            break
        heldout.add(g)
        count += groups[g]

    df["split"] = df["model_group"].map(lambda g: "heldout" if g in heldout else "tuning")

    # move each photo from public_research into its split folder
    photos = Path(args.photos)
    for _, row in df.iterrows():
        src = photos / "public_research" / row["file_name"]
        dst = photos / row["split"] / row["file_name"]
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dst)

    df.to_csv(args.labels, index=False)
    print(df.groupby("split").agg(photos=("file_name", "size"), models=("model_group", "nunique")).to_string())


if __name__ == "__main__":
    main()
