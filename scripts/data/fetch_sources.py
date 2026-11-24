import argparse
from pathlib import Path

from datasets import load_dataset
from huggingface_hub import snapshot_download

MOTOR_REV = "c0062cf8c9f7276c3dec48a43f2338c0bd41319a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="raw")
    args = ap.parse_args()
    out = Path(args.out)

    # main photo source, pinned to the revision recorded in image_index.csv
    snapshot_download("sergiudanstan/motor-nameplate", repo_type="dataset",
                      revision=MOTOR_REV, local_dir=out / "motor_nameplate")

    # same photos with a second label set, used only to cross-check
    snapshot_download("sergiudanstan/motor-nameplate-labels", repo_type="dataset",
                      local_dir=out / "motor_nameplate_labels")

    # 30 extra plates stored as parquet, so images are written out one by one
    darjja_dir = out / "darjja"
    darjja_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for split in ("train", "test"):
        ds = load_dataset("darjja/nameplate_sample2", split=split)
        for i, row in enumerate(ds):
            name = f"darjja_{split}_{i:02d}.png"
            row["image"].save(darjja_dir / name)
            rows.append((name, split, row.get("text", "").replace("\n", " | ")))
    with open(darjja_dir / "metadata.csv", "w", encoding="utf-8") as f:
        f.write("file_name,split,ocr_text\n")
        for name, split, text in rows:
            f.write(f'{name},{split},"{text.replace(chr(34), chr(39))}"\n')


if __name__ == "__main__":
    main()
