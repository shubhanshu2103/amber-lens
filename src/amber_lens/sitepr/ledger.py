"""Append-only SQLite ledger. Rows are never updated or deleted; Site PR state is rebuilt from them."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from amber_lens.schemas import LedgerEvent

from .state import next_status, rebuild

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    site_pr_id TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    payload TEXT NOT NULL,
    idempotency_key TEXT
);
CREATE INDEX IF NOT EXISTS events_by_pr ON events(site_pr_id, seq);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


class Ledger:
    def __init__(self, path: str | Path):
        self._path = str(path)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    @staticmethod
    def _row_to_event(r: tuple) -> LedgerEvent:
        return LedgerEvent(
            event_id=r[0],
            site_pr_id=r[1],
            type=r[2],
            actor=r[3],
            at=r[4],
            payload=json.loads(r[5]),
            idempotency_key=r[6],
        )

    def events(self, site_pr_id: str) -> list[LedgerEvent]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT event_id, site_pr_id, type, actor, at, payload, idempotency_key "
                "FROM events WHERE site_pr_id=? ORDER BY seq",
                (site_pr_id,),
            ).fetchall()
        finally:
            con.close()
        return [self._row_to_event(r) for r in rows]

    def site_pr_ids(self) -> list[str]:
        con = self._connect()
        try:
            return [r[0] for r in con.execute("SELECT DISTINCT site_pr_id FROM events ORDER BY site_pr_id")]
        finally:
            con.close()

    def append(self, event: LedgerEvent) -> None:
        """Validate the transition against current history and insert, atomically."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                rows = con.execute(
                    "SELECT event_id, site_pr_id, type, actor, at, payload, idempotency_key "
                    "FROM events WHERE site_pr_id=? ORDER BY seq",
                    (event.site_pr_id,),
                ).fetchall()
                history = [self._row_to_event(r) for r in rows]
                current = rebuild(history).status if history else None
                next_status(current, event.type)  # raises TransitionError if illegal
                con.execute(
                    "INSERT INTO events(event_id, site_pr_id, type, actor, at, payload, idempotency_key) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        event.event_id,
                        event.site_pr_id,
                        event.type,
                        event.actor,
                        event.at.isoformat(),
                        json.dumps(event.payload, sort_keys=True),
                        event.idempotency_key,
                    ),
                )
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
