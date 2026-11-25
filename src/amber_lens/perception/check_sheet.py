"""Local HTML check sheet so a person can verify AI-read labels against the photos.

Each photo sits next to its labels.csv values and every reader's value. The person marks each field
as label correct / label wrong / cannot tell, types the printed value when the label is wrong, and
downloads a CSV for the data owner. Tuning photos only; images are embedded so the page is one file.

How to run (after the spike has written its results):
    python -m amber_lens.perception.check_sheet --results docs/reader_spike_results.json
    then open .cache/perception/check_sheet.html in a browser
"""

from __future__ import annotations

import argparse
import base64
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

from amber_lens.perception.config import load_settings
from amber_lens.perception.dataset import DatasetError, load_tuning_labels, tuning_photo_path
from amber_lens.perception.fields import LABELLED_FIELDS

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


@dataclass(frozen=True)
class CheckRow:
    field: str
    label: str | None
    readings: dict[str, str | None]


@dataclass(frozen=True)
class CheckEntry:
    photo_id: str
    image_uri: str
    rows: tuple[CheckRow, ...]


def data_uri(path: Path) -> str:
    mime = _MIME.get(path.suffix.casefold())
    if mime is None:
        raise ValueError(f"unsupported image type: {path.name}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _cell(value: str | None) -> str:
    return '<span class="none">not given</span>' if value is None else escape(value)


def _row_html(photo_id: str, row: CheckRow, arms: list[str]) -> str:
    name = escape(f"{photo_id}|{row.field}")
    readings = "".join(f"<td>{_cell(row.readings.get(arm))}</td>" for arm in arms)
    choices = "".join(
        f'<label><input type="radio" name="{name}" value="{value}"> {text}</label>'
        for value, text in (("label_correct", "label correct"), ("label_wrong", "label wrong"),
                            ("cannot_tell", "cannot tell"))
    )
    return (
        f'<tr data-photo="{escape(photo_id)}" data-field="{escape(row.field)}" '
        f'data-label="{escape(row.label or "")}"><th>{escape(row.field)}</th><td class="label">{_cell(row.label)}</td>'
        f'{readings}<td class="choice">{choices}</td>'
        f'<td><input type="text" class="printed" placeholder="value as printed"></td></tr>'
    )


def render_check_sheet(entries: list[CheckEntry], arms: list[str]) -> str:
    head = "".join(f"<th>{escape(arm)}</th>" for arm in arms)
    sections = []
    for entry in entries:
        rows = "".join(_row_html(entry.photo_id, row, arms) for row in entry.rows)
        sections.append(
            f'<section><h2>{escape(entry.photo_id)}</h2><div class="pair">'
            f'<img src="{entry.image_uri}" alt="nameplate photo {escape(entry.photo_id)}">'
            f'<table><thead><tr><th>field</th><th>label</th>{head}<th>check</th><th>correction</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    return _PAGE.replace("{{SECTIONS}}", "".join(sections)).replace("{{COUNT}}", str(len(entries)))


def build_entries(results: dict, data_dir: Path) -> tuple[list[CheckEntry], list[str]]:
    """Entries for every photo in the spike results; photos resolve only through the tuning guard."""
    labels = load_tuning_labels(data_dir)
    arms = sorted({r["arm"] for r in results["readings"] if not r["arm"].startswith("vision+rule")})
    entries = []
    for photo_id in results["photos"]:
        if photo_id not in labels:
            raise DatasetError(f"{photo_id} is not a tuning photo")
        by_arm = {r["arm"]: r["values"] for r in results["readings"] if r["photo_id"] == photo_id}
        rows = tuple(
            CheckRow(field, labels[photo_id].truth[field], {arm: by_arm.get(arm, {}).get(field) for arm in arms})
            for field in LABELLED_FIELDS
        )
        entries.append(CheckEntry(photo_id, data_uri(tuning_photo_path(data_dir, labels[photo_id])), rows))
    return entries, arms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the label check sheet for the spike photos")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = load_settings()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    entries, arms = build_entries(results, settings.data_dir)
    out = args.out or settings.cache_dir / "check_sheet.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_check_sheet(entries, arms), encoding="utf-8")
    print(f"wrote {out} ({len(entries)} photos)")
    return 0


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label check sheet</title>
<style>
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #6b6b70; --line: #d9d9de; --accent: #1f5fbf; }
@media (prefers-color-scheme: dark) { :root { --bg: #161618; --fg: #f2f2f4; --muted: #a0a0a8; --line: #3a3a40;
  --accent: #7aa7ff; } }
body { background: var(--bg); color: var(--fg); font: 15px/1.45 system-ui, sans-serif; margin: 0 16px 64px; }
header { max-width: 1200px; margin: 24px auto; }
section { max-width: 1200px; margin: 0 auto 32px; border-top: 1px solid var(--line); padding-top: 12px; }
.pair { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
img { max-width: 420px; width: 100%; border: 1px solid var(--line); image-rendering: auto; }
table { border-collapse: collapse; flex: 1 1 560px; overflow-x: auto; display: block; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
td.label { font-weight: 600; }
.none { color: var(--muted); font-style: italic; }
.choice label { display: block; white-space: nowrap; }
input.printed { width: 12em; }
button { font: inherit; padding: 8px 16px; border: 1px solid var(--accent); color: var(--accent);
  background: transparent; border-radius: 6px; cursor: pointer; }
#status { color: var(--muted); margin-left: 12px; }
</style></head><body>
<header><h1>Label check sheet</h1>
<p>{{COUNT}} tuning photos. For each field, compare the <b>label</b> column with the photo and choose
label correct, label wrong (type the value exactly as printed), or cannot tell. Reader columns are
shown only as hints; they are not the truth either. Then download the CSV and send it to the data owner.</p>
<button id="download">Download CSV</button><span id="status"></span></header>
{{SECTIONS}}
<script>
function csvCell(v) { return '"' + String(v).replace(/"/g, '""') + '"'; }
document.getElementById('download').addEventListener('click', function () {
  var lines = ['photo_id,field,label_value,check,printed_value'];
  var unchecked = 0;
  document.querySelectorAll('tr[data-field]').forEach(function (tr) {
    var picked = tr.querySelector('input[type=radio]:checked');
    if (!picked) { unchecked += 1; }
    lines.push([tr.dataset.photo, tr.dataset.field, tr.dataset.label, picked ? picked.value : 'unchecked',
      tr.querySelector('input.printed').value].map(csvCell).join(','));
  });
  var blob = new Blob([lines.join('\\n') + '\\n'], {type: 'text/csv'});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'label_check.csv';
  a.click();
  document.getElementById('status').textContent = unchecked ? unchecked + ' fields still unchecked' : 'all fields checked';
});
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
