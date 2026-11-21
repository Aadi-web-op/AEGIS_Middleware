"""Locked facts in SQLite. Every change is a new row; the old row is kept as
`superseded`, so history (and "which answers used the old value") survives.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from threading import Lock

from app.facts.values import KINDS, Value, parse_value

LEVELS = {
    1: "Info",
    2: "Operational",
    3: "Commitment",
    4: "Regulated",
}
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")


@dataclass
class Fact:
    key: str
    label: str
    kind: str
    value: str          # as approved, e.g. "Rs 7,500" or "15 days"
    level: int
    unit: str | None = None          # only for kind="count"
    aliases: list[str] = field(default_factory=list)
    source: str | None = None
    version: str | None = None
    status: str = "active"           # active | superseded | retired
    id: int | None = None
    created_at: str | None = None
    created_by: str | None = None
    supersedes_id: int | None = None

    def parsed(self) -> Value:
        return parse_value(self.value, self.kind, self.unit)

    def phrases(self) -> list[str]:
        return [p for p in [self.label, *self.aliases] if p and p.strip()]

    def public(self) -> dict:
        data = asdict(self)
        data["level_name"] = LEVELS.get(self.level, "")
        return data


def validate(fact: Fact) -> None:
    if not _KEY_RE.match(fact.key):
        raise ValueError("key must be 2-64 chars: lowercase letters, digits, '_', '-', '.'")
    if fact.kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if fact.level not in LEVELS:
        raise ValueError("level must be 1, 2, 3 or 4")
    if not fact.label.strip():
        raise ValueError("label is required")
    if fact.kind == "count" and not (fact.unit or "").strip():
        raise ValueError("count facts need a unit word, e.g. 'characters'")
    fact.parsed()  # raises ValueError when the value does not parse cleanly


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class FactStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("AEGIS_FACTS_DB_PATH", "facts.db")
        self._lock = Lock()
        self._memory = self.path == ":memory:"
        self._shared = sqlite3.connect(self.path, check_same_thread=False) if self._memory else None
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    unit TEXT,
                    level INTEGER NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    source TEXT,
                    version TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    supersedes_id INTEGER REFERENCES facts(id)
                );
                CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key, status);
                """
            )
        self._cache: list[Fact] | None = None

    def _connect(self) -> sqlite3.Connection:
        db = self._shared if self._memory else sqlite3.connect(self.path, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"], key=row["key"], label=row["label"], kind=row["kind"],
            value=row["value"], unit=row["unit"], level=row["level"],
            aliases=json.loads(row["aliases"] or "[]"), source=row["source"],
            version=row["version"], status=row["status"], created_at=row["created_at"],
            created_by=row["created_by"], supersedes_id=row["supersedes_id"],
        )

    def _insert(self, db: sqlite3.Connection, fact: Fact) -> Fact:
        fact.created_at = _now()
        cur = db.execute(
            "INSERT INTO facts (key, label, kind, value, unit, level, aliases, source, version,"
            " status, created_at, created_by, supersedes_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (fact.key, fact.label.strip(), fact.kind, fact.value.strip(), fact.unit, fact.level,
             json.dumps([a.strip() for a in fact.aliases if a.strip()]), fact.source,
             fact.version, fact.created_at, fact.created_by, fact.supersedes_id),
        )
        fact.id, fact.status = cur.lastrowid, "active"
        return fact

    # ------------------------------------------------------------------ reads
    def active(self) -> list[Fact]:
        if self._cache is None:
            with self._connect() as db:
                rows = db.execute("SELECT * FROM facts WHERE status = 'active' ORDER BY key").fetchall()
            self._cache = [self._row(r) for r in rows]
        return list(self._cache)

    def get(self, key: str) -> Fact | None:
        return next((f for f in self.active() if f.key == key), None)

    def history(self, key: str) -> list[Fact]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM facts WHERE key = ? ORDER BY id DESC", (key,)).fetchall()
        return [self._row(r) for r in rows]

    def previous_values(self) -> dict[str, list[Fact]]:
        """Superseded versions per key, newest first (to spot outdated answers)."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM facts WHERE status = 'superseded' ORDER BY id DESC").fetchall()
        out: dict[str, list[Fact]] = {}
        for row in rows:
            fact = self._row(row)
            out.setdefault(fact.key, []).append(fact)
        return out

    # ----------------------------------------------------------------- writes
    def create(self, fact: Fact) -> Fact:
        validate(fact)
        with self._lock, self._connect() as db:
            if db.execute("SELECT 1 FROM facts WHERE key = ? AND status = 'active'",
                          (fact.key,)).fetchone():
                raise KeyError(f"fact {fact.key!r} already exists; update it instead")
            created = self._insert(db, fact)
        self._cache = None
        return created

    def update(self, key: str, *, created_by: str | None = None, **changes) -> tuple[Fact, Fact]:
        """New version of a fact. Returns (old, new)."""
        old = self.get(key)
        if old is None:
            raise LookupError(f"no active fact {key!r}")
        allowed = {"label", "value", "unit", "level", "aliases", "source", "version"}
        new = Fact(**{**asdict(old), **{k: v for k, v in changes.items()
                                         if k in allowed and v is not None}})
        new.id, new.created_by, new.supersedes_id = None, created_by, old.id
        validate(new)
        with self._lock, self._connect() as db:
            db.execute("UPDATE facts SET status = 'superseded' WHERE id = ?", (old.id,))
            self._insert(db, new)
        old.status = "superseded"
        self._cache = None
        return old, new

    def retire(self, key: str) -> bool:
        with self._lock, self._connect() as db:
            cur = db.execute("UPDATE facts SET status = 'retired' WHERE key = ? AND status = 'active'",
                             (key,))
        self._cache = None
        return cur.rowcount > 0
