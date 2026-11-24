import argparse
import hashlib
from pathlib import Path

import pandas as pd

PRIORITY_FILES = {
    "01.jpg", "02.jpg", "04.jpg", "05.jpg", "06.jpg", "09.jpg", "011.jpg", "012.jpg", "013.jpg",
    "014.jpg", "019.jpg", "020.jpg", "021.jpg", "022.jpg", "025.jpg", "026.jpg", "031.jpg",
    "032.jpg", "035.jpg", "036.jpg", "037.jpg", "038.jpg", "041.jpg", "044.jpg", "047.jpg",
    "048.jpg", "049.jpg", "052.jpg", "053.jpg", "057.jpg", "061.jpg", "062.jpg", "063.jpg",
    "066.jpg", "068.jpg", "069.jpg", "070.jpg", "072.jpg", "073.jpg", "075.jpg", "076.jpg",
    "077.jpg",
}
TEMPLATE_HINTS = ("HOW TO READ", "NOTE: NAMEPLATES", "SERIAL NUMBER AND/OR DATE", "MANUFACTURER'S NAME OR LOGO")


def find_metadata(root):
    for name in ("metadata.csv", "metadata.jsonl"):
        hits = list(Path(root).rglob(name))
        if hits:
            return hits[0]
    raise SystemExit(f"no metadata file under {root}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw/motor_nameplate")
    ap.add_argument("--out", default="work/candidates.csv")
    ap.add_argument("--min-conf", type=float, default=0.9)
    args = ap.parse_args()

    meta_path = find_metadata(args.raw)
    df = pd.read_csv(meta_path) if meta_path.suffix == ".csv" else pd.read_json(meta_path, lines=True)
    file_col = next(c for c in ("file_name", "filename", "image", "file") if c in df.columns)
    img_dir = meta_path.parent

    # keep rows whose own OCR claims a model number, a voltage and one more rating
    has_rating = df[["amps", "hp", "kw"]].notna().any(axis=1) if {"amps", "hp", "kw"} <= set(df.columns) else True
    keep = df["model_or_cat_no"].notna() & df["volts"].notna() & has_rating
    if "confidence" in df.columns:
        keep &= df["confidence"].fillna(0) >= args.min_conf
    raw_text = df.get("raw_text", pd.Series([""] * len(df))).fillna("").str.upper()
    keep &= ~raw_text.apply(lambda t: any(h in t for h in TEMPLATE_HINTS))
    cand = df[keep].copy()

    # drop byte-identical images, keeping the first copy
    def md5(fn):
        p = img_dir / fn
        return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None
    cand["md5"] = cand[file_col].map(md5)
    cand = cand[cand["md5"].notna()].drop_duplicates("md5")

    cand["priority"] = cand[file_col].isin(PRIORITY_FILES)
    cand = cand.sort_values(["priority", file_col], ascending=[False, True])
    cand = cand.rename(columns={file_col: "file_name"})
    cand.insert(1, "image_path", cand["file_name"].map(lambda f: str(img_dir / f)))
    ocr_cols = [c for c in ("manufacturer_label", "model_or_cat_no", "volts", "amps", "hp", "kw", "hz", "phase", "confidence") if c in cand.columns]
    cand = cand[["file_name", "image_path", "priority", "md5"] + ocr_cols].rename(columns={c: f"ocr_{c}" for c in ocr_cols})

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cand.to_csv(args.out, index=False)
    print(f"{len(cand)} candidates written to {args.out} ({int(cand['priority'].sum())} from the priority list)")


if __name__ == "__main__":
    main()
