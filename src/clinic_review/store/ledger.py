"""The ledger: every evaluation run's cohort split, rule results, and skips.

It lives in the same SQLite file as the raw store, under the separate macOS account. Rows
carry CHR ids, rule ids, states, and dates, never names or chart text, so nothing here is
sealed: aggregates have to be queryable. Each run records a digest of the rules and value
sets it used, so two runs can be diffed knowing whether the logic changed in between.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id       TEXT PRIMARY KEY,
    sweep        TEXT NOT NULL,
    as_of        TEXT NOT NULL,
    ruleset      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE TABLE IF NOT EXISTS cohort (
    run_id       TEXT NOT NULL,
    chr_id       TEXT NOT NULL,
    grp          TEXT NOT NULL,
    reason       TEXT NOT NULL,
    PRIMARY KEY (run_id, chr_id)
);
CREATE TABLE IF NOT EXISTS results (
    run_id       TEXT NOT NULL,
    chr_id       TEXT NOT NULL,
    rule_id      TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    state        TEXT NOT NULL,
    due_date     TEXT,
    evidence_ids TEXT NOT NULL,
    searched     TEXT NOT NULL,
    missing      TEXT NOT NULL,
    reason       TEXT NOT NULL,
    PRIMARY KEY (run_id, chr_id, rule_id)
);
CREATE TABLE IF NOT EXISTS skips (
    run_id         TEXT NOT NULL,
    chr_id         TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    source         TEXT NOT NULL,
    reason         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_run_modes (
    run_id TEXT PRIMARY KEY,
    cohort_only INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_rule_metadata (
    run_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    action_note TEXT NOT NULL,
    PRIMARY KEY (run_id, rule_id)
);
"""

GROUPS = ("active", "outreach", "excluded", "not_walked")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self._db = sqlite3.connect(Path(path))
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def start(self, run_id: str, sweep: str, as_of: str, ruleset: str, *, rules=None, cohort_only=False) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO eval_runs (run_id, sweep, as_of, ruleset, started_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, sweep, as_of, ruleset, _now()),
            )
            if rules is not None:
                # Queue instructions must describe this run, even after a rule is edited.
                self._db.execute("INSERT INTO eval_run_modes VALUES (?, ?)", (run_id, int(cohort_only)))
                self._db.executemany(
                    "INSERT INTO eval_rule_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(run_id, r.id, r.version, r.title, r.category, r.status,
                      (r.action or {}).get("kind", ""), (r.action or {}).get("note", ""))
                     for r in rules.values()],
                )

    def finish(self, run_id: str) -> None:
        with self._db:
            self._db.execute("UPDATE eval_runs SET finished_at = ? WHERE run_id = ?", (_now(), run_id))

    def add_patient(self, run_id: str, chr_id: str, group: str, reason: str, results=(), skips=()) -> None:
        if group not in GROUPS:
            raise ValueError(f"unknown cohort group {group!r}")
        with self._db:
            self._db.execute("INSERT INTO cohort VALUES (?, ?, ?, ?)", (run_id, chr_id, group, reason))
            self._db.executemany(
                "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        chr_id,
                        r.rule_id,
                        r.rule_version,
                        r.state.value,
                        r.due_date.isoformat() if r.due_date else None,
                        " ".join(r.evidence_ids),
                        " ".join(r.searched_sources),
                        "; ".join(r.missing_inputs),
                        r.reason,
                    )
                    for r in results
                ],
            )
            self._db.executemany(
                "INSERT INTO skips VALUES (?, ?, ?, ?, ?)",
                [(run_id, chr_id, s.observation_id, s.source, s.reason) for s in skips],
            )

    # aggregates only: nothing below returns a CHR id

    def cohort_counts(self, run_id: str) -> dict[str, int]:
        rows = self._db.execute("SELECT grp, COUNT(*) FROM cohort WHERE run_id = ? GROUP BY grp", (run_id,))
        counts = dict.fromkeys(GROUPS, 0)
        counts.update(dict(rows.fetchall()))
        return counts

    def state_counts(self, run_id: str) -> dict[str, Counter]:
        out: dict[str, Counter] = {}
        rows = self._db.execute(
            "SELECT rule_id, state, COUNT(*) FROM results WHERE run_id = ? GROUP BY rule_id, state ORDER BY rule_id",
            (run_id,),
        )
        for rule_id, state, n in rows:
            out.setdefault(rule_id, Counter())[state] = n
        return out

    def skip_counts(self, run_id: str, top: int = 15) -> list[tuple[str, int]]:
        rows = self._db.execute(
            "SELECT reason, COUNT(*) FROM skips WHERE run_id = ? GROUP BY reason ORDER BY COUNT(*) DESC, reason LIMIT ?",
            (run_id, top),
        )
        return rows.fetchall()

    def state_of(self, run_id: str, chr_id: str, rule_id: str) -> str | None:
        """One patient's state for one rule. For tests and the queue, never for printing."""
        row = self._db.execute(
            "SELECT state FROM results WHERE run_id = ? AND chr_id = ? AND rule_id = ?", (run_id, chr_id, rule_id)
        ).fetchone()
        return row[0] if row else None

    def group_of(self, run_id: str, chr_id: str) -> str | None:
        row = self._db.execute("SELECT grp FROM cohort WHERE run_id = ? AND chr_id = ?", (run_id, chr_id)).fetchone()
        return row[0] if row else None
