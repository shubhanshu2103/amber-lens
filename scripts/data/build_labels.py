import argparse
import re
import shutil
from pathlib import Path

import pandas as pd

HF_URL = "https://huggingface.co/datasets/sergiudanstan/motor-nameplate/resolve/c0062cf8c9f7276c3dec48a43f2338c0bd41319a/"
DARJJA_URL = "https://huggingface.co/datasets/darjja/nameplate_sample2"

COLUMNS = ["image_id", "photo_id", "file_name", "source", "source_url", "license", "model_group",
           "manufacturer", "model_number", "equipment_type", "rating_1", "rating_2", "frequency", "power",
           "voltage", "amps", "hp_or_kw", "readable", "true_verdict", "planted_problem", "quality", "angle",
           "lighting", "glare", "obscured", "small_text", "split", "verified_by", "human_checked", "notes"]


def norm(s):
    return re.sub(r"[^0-9A-Z]", "", str(s).upper().replace(",", "."))


def ocr_note(row, ocr):
    # record the dataset OCR whenever it disagrees with what was read off the photo
    if ocr is None:
        return ""
    diffs = []
    if norm(ocr.get("model_or_cat_no", "")) != norm(row["model_number"]):
        diffs.append(f"model {ocr.get('model_or_cat_no', '')}")
    if norm(ocr.get("volts", "")) not in norm(row["voltage"]):
        diffs.append(f"volts {ocr.get('volts', '')}")
    if row["amps"] and norm(ocr.get("amps", "")) not in norm(row["amps"]):
        diffs.append(f"amps {ocr.get('amps', '')}")
    return f"dataset OCR differs: {'; '.join(diffs)}" if diffs else ""


def split_rating(r1, r2):
    # rating_1 is always a voltage; rating_2 is a current unless the plate gave none
    volts, amps = r1, r2 if re.search(r"\bA\b", r2) else ""
    m1, m2 = re.match(r"(.+?) / (.+? A) \((\w+)\)", r1), re.match(r"(.+?) / (.+? A) \((\w+)\)", r2)
    if m1 and m2:
        volts = f"{m1.group(1)} ({m1.group(3)}) / {m2.group(1)} ({m2.group(3)})"
        amps = f"{m1.group(2)} / {m2.group(2)}"
    elif "(primary)" in r1:
        volts, amps = f"{r1} / {r2}", ""
    return volts, amps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default="data/metadata/photo_review.csv")
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="data/labels.csv")
    ap.add_argument("--photos", default="data/photos/public_research")
    args = ap.parse_args()

    review = pd.read_csv(args.review, dtype=str).fillna("")
    meta = pd.read_csv(Path(args.raw) / "motor_nameplate" / "metadata.csv", dtype=str).fillna("")
    ocr_by_file = {r["file_name"]: r for r in meta.to_dict("records")}

    rows = []
    for r in review[review["decision"].isin(["KEEP", "CANT_MATCH"])].to_dict("records"):
        hf = r["source"] == "hf"
        stem = r["orig"].rsplit(".", 1)[0]
        file_name = f"hf_{r['orig']}" if hf else r["orig"]
        readable = r["decision"] == "KEEP"
        volts, amps = split_rating(r["rating_1"], r["rating_2"]) if readable else ("", "")
        row = {
            "image_id": f"hf_{stem}" if hf else stem,
            "file_name": file_name,
            "source": "sergiudanstan/motor-nameplate" if hf else "darjja/nameplate_sample2",
            "source_url": HF_URL + r["orig"] if hf else f"{DARJJA_URL} ({stem.split('_')[1]} split, row {int(stem.split('_')[2])})",
            "license": "MIT (dataset card); original photo provenance unknown",
            "model_group": r["model_number"].upper().replace(" ", "") if readable else f"UNREADABLE_{stem.upper()}",
            "manufacturer": r["manufacturer"],
            "model_number": r["model_number"],
            "equipment_type": r["equipment_type"],
            "rating_1": r["rating_1"],
            "rating_2": r["rating_2"],
            "frequency": r["frequency"],
            "power": r["power"],
            "voltage": volts,
            "amps": amps,
            "hp_or_kw": r["power"],
            "readable": "yes" if readable else "no",
            "true_verdict": "" if readable else "CANT_MATCH",
            "planted_problem": "",
            "quality": r["quality"], "angle": r["angle"], "lighting": r["lighting"], "glare": r["glare"],
            "obscured": r["obscured"], "small_text": r["small_text"],
            "split": "",
            "verified_by": "claude-code-vision",
            "human_checked": "",
        }
        row["photo_id"] = row["image_id"]
        extra = ocr_note(row, ocr_by_file.get(r["orig"])) if hf and readable else ""
        row["notes"] = "; ".join(x for x in (r["notes"], extra) if x)
        rows.append(row)

        src = Path(args.raw) / ("motor_nameplate" if hf else "darjja") / r["orig"]
        Path(args.photos).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, Path(args.photos) / file_name)

    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_csv(args.out, index=False)
    print(f"{len(df)} rows written to {args.out}: {int((df['readable'] == 'yes').sum())} readable, "
          f"{int((df['readable'] == 'no').sum())} CANT_MATCH, {df['model_group'].nunique()} model groups")


if __name__ == "__main__":
    main()
