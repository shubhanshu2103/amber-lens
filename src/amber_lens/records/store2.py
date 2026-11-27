"""Project Alpha record store: CSVs -> SQLite, lookups by model number.

Every lookup returns the record plus how it matched: exact, normalised, alias or fuzzy.
Only "exact" and "normalised" are safe to treat as the same model; "alias" means an approved
equivalent suffix; "fuzzy" is a hint only and must never produce a GO on its own.
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Generic, Literal, TypeVar

from amber_lens.schemas import Delivery, POLine, ScheduleItem, Sighting, Submittal

MatchType = Literal["exact", "normalised", "alias", "fuzzy"]
T = TypeVar("T")
FUZZY_MIN = 0.88

_SCHEMA = """
CREATE TABLE po_lines (po_number TEXT, line INTEGER, equipment_tag TEXT, model_number TEXT,
  description TEXT, qty INTEGER, submittal_id TEXT, PRIMARY KEY (po_number, line));
CREATE TABLE submittals (submittal_id TEXT PRIMARY KEY, model_number TEXT, status TEXT,
  datasheet_path TEXT, datasheet_source_url TEXT, ratings TEXT, allowed_suffixes TEXT);
CREATE TABLE schedule (equipment_tag TEXT PRIMARY KEY, model_number TEXT, room_tag TEXT,
  drawing_ref TEXT, activity_id TEXT, float_days INTEGER);
CREATE TABLE rooms (room_tag TEXT PRIMARY KEY, room_name TEXT, floor TEXT, zone TEXT);
CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, po_number TEXT, line INTEGER,
  qty_received INTEGER, status TEXT);
CREATE TABLE sightings (model_number TEXT, equipment_tag TEXT, room_tag TEXT,
  observation_id TEXT, seen_at TEXT);
"""


def normalise(model: str | None) -> str:
    """Uppercase and drop everything except letters and digits: 'm-3538' == 'M 3538'."""
    return re.sub(r"[^A-Z0-9]", "", (model or "").upper())


@dataclass(frozen=True)
class Match(Generic[T]):
    item: T
    match_type: MatchType
    score: float = 1.0


def _none(v: str | None) -> str | None:
    return v if v not in (None, "") else None


class RecordStore:
    def __init__(self, db: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(db))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    @classmethod
    def from_csv_dir(cls, folder: str | Path, db: str | Path = ":memory:") -> RecordStore:
        store = cls(db)
        folder = Path(folder)
        for table in ("po_lines", "submittals", "schedule", "rooms", "deliveries"):
            path = folder / f"{table}.csv"
            if not path.exists():
                continue
            with path.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    cols = list(row)
                    store.db.execute(
                        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [_none(row[c]) for c in cols],
                    )
        store.db.commit()
        return store

    # ---- row -> model -------------------------------------------------------------------
    @staticmethod
    def _po(r: sqlite3.Row) -> POLine:
        return POLine(po_number=r["po_number"], line=r["line"], equipment_tag=r["equipment_tag"],
                      model_number=r["model_number"], description=r["description"] or "",
                      qty=r["qty"], submittal_id=r["submittal_id"])

    @staticmethod
    def _sub(r: sqlite3.Row) -> Submittal:
        suffixes = [s for s in (r["allowed_suffixes"] or "").split("|") if s]
        return Submittal(submittal_id=r["submittal_id"], model_number=r["model_number"],
                         status=r["status"], datasheet_path=r["datasheet_path"],
                         datasheet_source_url=r["datasheet_source_url"],
                         ratings=json.loads(r["ratings"] or "{}"), allowed_suffixes=suffixes)

    @staticmethod
    def _sched(r: sqlite3.Row) -> ScheduleItem:
        return ScheduleItem(equipment_tag=r["equipment_tag"], model_number=r["model_number"],
                            room_tag=r["room_tag"], drawing_ref=r["drawing_ref"],
                            activity_id=r["activity_id"], float_days=r["float_days"])

    # ---- matching -----------------------------------------------------------------------
    def _match_model(self, table: str, model: str, build) -> list[Match]:
        """All rows of `table` whose model matches, best match type first."""
        rows = self.db.execute(f"SELECT * FROM {table}").fetchall()
        key = normalise(model)
        if not key:
            return []
        alias_ok = self._alias_map()
        exact, norm, alias, fuzzy = [], [], [], []
        for r in rows:
            rm = r["model_number"] or ""
            rk = normalise(rm)
            if rm == model:
                exact.append(Match(build(r), "exact"))
            elif rk == key:
                norm.append(Match(build(r), "normalised"))
            elif key in alias_ok.get(rk, ()):
                alias.append(Match(build(r), "alias"))
            else:
                score = difflib.SequenceMatcher(None, key, rk).ratio()
                if score >= FUZZY_MIN:
                    fuzzy.append(Match(build(r), "fuzzy", round(score, 3)))
        for bucket in (exact, norm, alias):
            if bucket:
                return bucket
        return sorted(fuzzy, key=lambda m: -m.score)

    def _alias_map(self) -> dict[str, set[str]]:
        """normalised approved model -> {normalised model+suffix, ...} from allowed suffixes."""
        out: dict[str, set[str]] = {}
        for r in self.db.execute("SELECT model_number, allowed_suffixes FROM submittals"):
            base = normalise(r["model_number"])
            for suf in (r["allowed_suffixes"] or "").split("|"):
                if suf:
                    out.setdefault(base, set()).add(base + normalise(suf))
        return out

    # ---- lookups (issue #13) ------------------------------------------------------------
    def po_lines(self, model: str) -> list[Match[POLine]]:
        return self._match_model("po_lines", model, self._po)

    def submittal_for_model(self, model: str) -> Match[Submittal] | None:
        hits = self._match_model("submittals", model, self._sub)
        return hits[0] if hits else None

    def schedule_rows(self, model: str) -> list[Match[ScheduleItem]]:
        return self._match_model("schedule", model, self._sched)

    def po_line(self, po_number: str, line: int) -> POLine | None:
        r = self.db.execute("SELECT * FROM po_lines WHERE po_number=? AND line=?",
                            (po_number, line)).fetchone()
        return self._po(r) if r else None

    def room_tags(self) -> set[str]:
        return {r["room_tag"] for r in self.db.execute("SELECT room_tag FROM rooms")}

    # ---- deliveries (gate check) -------------------------------------------------------
    def deliveries(self, po_number: str, line: int) -> list[Delivery]:
        rows = self.db.execute(
            "SELECT * FROM deliveries WHERE po_number=? AND line=? ORDER BY delivery_id",
            (po_number, line),
        ).fetchall()
        return [Delivery(delivery_id=r["delivery_id"], po_number=r["po_number"], line=r["line"],
                         qty_received=r["qty_received"], status=r["status"] or "expected")
                for r in rows]

    def received_so_far(self, po_number: str, line: int, exclude_ticket_id: str | None = None) -> int:
        """Quantity already received on this PO line (status received or partial).

        A delivery whose delivery_id equals `exclude_ticket_id` is left out.
        """
        return sum(
            d.qty_received or 0
            for d in self.deliveries(po_number, line)
            if d.status in ("received", "partial") and d.delivery_id != exclude_ticket_id
        )

    # ---- sightings (#14) ----------------------------------------------------------------
    def add_sighting(self, s: Sighting) -> None:
        self.db.execute(
            "INSERT INTO sightings (model_number, equipment_tag, room_tag, observation_id, seen_at)"
            " VALUES (?,?,?,?,?)",
            (s.model_number, s.equipment_tag, s.room_tag, s.observation_id, s.seen_at.isoformat()),
        )
        self.db.commit()

    def sightings_for_model(
        self, model_number: str, since: datetime | None = None
    ) -> list[Sighting]:
        """Every sighting of this model (same normalised match), newest first.

        `since` keeps only sightings at or after that time.
        """
        key = normalise(model_number)
        if not key:
            return []
        out = []
        for r in self.db.execute("SELECT * FROM sightings"):
            if normalise(r["model_number"]) != key:
                continue
            s = Sighting(model_number=r["model_number"], equipment_tag=r["equipment_tag"],
                         room_tag=r["room_tag"], observation_id=r["observation_id"],
                         seen_at=datetime.fromisoformat(r["seen_at"]))
            if since is None or s.seen_at >= since:
                out.append(s)
        return sorted(out, key=lambda s: s.seen_at, reverse=True)

    def sightings_last_days(
        self, model_number: str, days: int, now: datetime | None = None
    ) -> list[Sighting]:
        """Where was this model seen in the last `days` days?"""
        now = now or datetime.now(UTC)
        return self.sightings_for_model(model_number, since=now - timedelta(days=days))
