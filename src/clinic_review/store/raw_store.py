"""Raw capture store: every response the walker keeps, exactly as received, sealed.

Plain columns hold only what's needed to find and resume work: run id, CHR id, screen
name, status, content type, timestamps and a body hash. URLs and bodies are sealed.

Keeping raw bodies means parsers can be fixed and rerun without walking a chart again.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .crypto import KeyProvider, Sealer

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    sweep        TEXT NOT NULL,
    profile      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    outcome      TEXT
);
CREATE TABLE IF NOT EXISTS captures (
    id           INTEGER PRIMARY KEY,
    run_id       TEXT NOT NULL,
    chr_id       TEXT NOT NULL,
    screen       TEXT NOT NULL,
    status       INTEGER NOT NULL,
    content_type TEXT,
    captured_at  TEXT NOT NULL,
    url_sealed   BLOB NOT NULL,
    body_sealed  BLOB NOT NULL,
    body_sha256  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS captures_patient ON captures (chr_id, screen);
CREATE TABLE IF NOT EXISTS audit (
    run_id       TEXT NOT NULL,
    chr_id       TEXT NOT NULL,
    screen       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL,
    kept         INTEGER NOT NULL,
    dropped      INTEGER NOT NULL,
    outcome      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster (
    chr_id       TEXT PRIMARY KEY,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    sweep        TEXT NOT NULL,
    pass         TEXT NOT NULL,
    chr_id       TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    done_at      TEXT NOT NULL,
    PRIMARY KEY (sweep, pass, chr_id)
);
"""

ROSTER_ID = "_roster"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _aad(chr_id: str, screen: str, part: str) -> bytes:
    return f"{chr_id}|{screen}|{part}".encode()


@dataclass(frozen=True)
class Capture:
    chr_id: str
    screen: str
    status: int
    content_type: str | None
    captured_at: str
    url: str
    body: bytes


class RawStore:
    def __init__(self, path: str | Path, keys: KeyProvider) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.executescript(SCHEMA)
        self._sealer = Sealer(keys.get_key())

    def close(self) -> None:
        self._db.close()

    # runs

    def start_run(self, run_id: str, kind: str, sweep: str, profile: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO runs (run_id, kind, sweep, profile, started_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, kind, sweep, profile, _now()),
            )

    def finish_run(self, run_id: str, outcome: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
                (_now(), outcome, run_id),
            )

    # captures

    def add_capture(
        self,
        *,
        run_id: str,
        chr_id: str,
        screen: str,
        url: str,
        status: int,
        content_type: str | None,
        body: bytes,
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO captures (run_id, chr_id, screen, status, content_type, captured_at,"
                " url_sealed, body_sealed, body_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    chr_id,
                    screen,
                    status,
                    content_type,
                    _now(),
                    self._sealer.seal(url.encode(), _aad(chr_id, screen, "url")),
                    self._sealer.seal(body, _aad(chr_id, screen, "body")),
                    hashlib.sha256(body).hexdigest(),
                ),
            )

    def captures(self, chr_id: str, screen: str | None = None) -> Iterator[Capture]:
        sql = (
            "SELECT chr_id, screen, status, content_type, captured_at, url_sealed, body_sealed"
            " FROM captures WHERE chr_id = ?"
        )
        args: tuple = (chr_id,)
        if screen is not None:
            sql += " AND screen = ?"
            args += (screen,)
        for cid, scr, status, ctype, at, url_s, body_s in self._db.execute(sql + " ORDER BY id", args):
            yield Capture(
                chr_id=cid,
                screen=scr,
                status=status,
                content_type=ctype,
                captured_at=at,
                url=self._sealer.open(url_s, _aad(cid, scr, "url")).decode(),
                body=self._sealer.open(body_s, _aad(cid, scr, "body")),
            )

    # audit

    def audit(
        self,
        *,
        run_id: str,
        chr_id: str,
        screen: str,
        started_at: str,
        kept: int,
        dropped: int,
        outcome: str,
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO audit (run_id, chr_id, screen, started_at, finished_at, kept, dropped, outcome)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, chr_id, screen, started_at, _now(), kept, dropped, outcome),
            )

    # roster and progress

    def upsert_roster(self, chr_ids: Iterable[str]) -> None:
        now = _now()
        with self._db:
            self._db.executemany(
                "INSERT INTO roster (chr_id, first_seen, last_seen) VALUES (?, ?, ?)"
                " ON CONFLICT (chr_id) DO UPDATE SET last_seen = excluded.last_seen",
                [(cid, now, now) for cid in chr_ids],
            )

    def roster_ids(self) -> list[str]:
        return [row[0] for row in self._db.execute("SELECT chr_id FROM roster ORDER BY chr_id")]

    def mark_done(self, sweep: str, pass_name: str, chr_id: str, run_id: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO progress (sweep, pass, chr_id, run_id, done_at) VALUES (?, ?, ?, ?, ?)",
                (sweep, pass_name, chr_id, run_id, _now()),
            )

    def done_ids(self, sweep: str, pass_name: str) -> set[str]:
        rows = self._db.execute("SELECT chr_id FROM progress WHERE sweep = ? AND pass = ?", (sweep, pass_name))
        return {row[0] for row in rows}

    def summary(self) -> dict[str, int]:
        q = lambda sql: self._db.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "roster": q("SELECT COUNT(*) FROM roster"),
            "captures": q("SELECT COUNT(*) FROM captures"),
            "patients_captured": q("SELECT COUNT(DISTINCT chr_id) FROM captures WHERE chr_id != '_roster'"),
            "screens_visited": q("SELECT COUNT(*) FROM audit"),
            "screens_failed": q("SELECT COUNT(*) FROM audit WHERE outcome != 'ok'"),
            "dropped": q("SELECT COALESCE(SUM(dropped), 0) FROM audit"),
            "runs": q("SELECT COUNT(*) FROM runs"),
        }
