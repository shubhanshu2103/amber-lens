"""Mock procurement record store. Stands in for Amber's own API.

`apply` is idempotent on the key: a key already seen is skipped. The key and the changes are committed in one
transaction, so a crash can never leave one without the other.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from amber_lens.schemas import RecordChange

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applied_keys (key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS records (
    record_kind TEXT NOT NULL, record_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT,
    PRIMARY KEY (record_kind, record_id, field)
);
CREATE TABLE IF NOT EXISTS write_log (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL);
"""


class MockRecordStore:
    def __init__(self, path: str | Path):
        self._path = str(path)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def seed(self, record_kind: str, record_id: str, field: str, value: str | None) -> None:
        con = self._connect()
        try:
            con.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)", (record_kind, record_id, field, value))
        finally:
            con.close()

    def apply(self, key: str, changes: list[RecordChange]) -> bool:
        """Apply changes once per key. Returns True if applied now, False if the key was already seen."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                if con.execute("SELECT 1 FROM applied_keys WHERE key=?", (key,)).fetchone():
                    con.execute("ROLLBACK")
                    return False
                for c in changes:
                    con.execute(
                        "INSERT OR REPLACE INTO records VALUES (?,?,?,?)",
                        (c.record_kind, c.record_id, c.field, c.new_value),
                    )
                con.execute("INSERT INTO applied_keys VALUES (?)", (key,))
                con.execute("INSERT INTO write_log(key) VALUES (?)", (key,))
                con.execute("COMMIT")
                return True
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    def read(self, record_kind: str, record_id: str, field: str) -> str | None:
        """Read-back path used by verify; deliberately separate from `apply`."""
        con = self._connect()
        try:
            row = con.execute(
                "SELECT value FROM records WHERE record_kind=? AND record_id=? AND field=?",
                (record_kind, record_id, field),
            ).fetchone()
        finally:
            con.close()
        return row[0] if row else None

    def write_count(self, key: str) -> int:
        con = self._connect()
        try:
            return con.execute("SELECT COUNT(*) FROM write_log WHERE key=?", (key,)).fetchone()[0]
        finally:
            con.close()
