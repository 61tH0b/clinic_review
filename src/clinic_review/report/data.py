"""Read completed ledger runs without opening the raw-store key or changing the database."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..engine.states import State


class ReportError(ValueError):
    """Fixed messages only: neither paths nor patient content belong in CLI errors."""


@dataclass(frozen=True)
class Run:
    run_id: str
    as_of: date
    ruleset: str
    rows: tuple[dict[str, str], ...]
    cohort: tuple[dict[str, str], ...]


def read_run(path: str | Path, run_id: str) -> Run:
    try:
        # mode=ro also prevents a misspelled store path creating an empty database.
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")  # One consistent snapshot across all three reads.
            meta = db.execute("SELECT * FROM eval_runs WHERE run_id=?", (run_id,)).fetchone()
            if meta is None or not meta["finished_at"]:
                raise ReportError("Run doesn't exist or hasn't finished.")
            mode = db.execute("SELECT cohort_only FROM eval_run_modes WHERE run_id=?", (run_id,)).fetchone()
            if mode is None:
                raise ReportError("Run has no rule snapshots; re-evaluate before exporting.")
            if mode[0]:
                raise ReportError("Cohort-only runs can't produce worklists or rule diffs.")
            cohort = tuple(dict(r) for r in db.execute(
                "SELECT chr_id AS patient_id, grp AS cohort_group, reason FROM cohort WHERE run_id=? ORDER BY chr_id",
                (run_id,),
            ))
            snapshots = db.execute("SELECT COUNT(*) FROM eval_rule_metadata WHERE run_id=?", (run_id,)).fetchone()[0]
            expected = sum(r["cohort_group"] == "active" for r in cohort) * snapshots
            count = db.execute("SELECT COUNT(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0]
            rows = tuple(dict(r) for r in db.execute(
                """SELECT r.chr_id AS patient_id, r.rule_id, CAST(r.rule_version AS TEXT) AS rule_version,
                          m.title AS rule_title, m.category, m.status AS rule_status, r.state,
                          COALESCE(r.due_date, '') AS due_date, r.evidence_ids,
                          r.searched AS searched_sources, r.missing AS missing_inputs, r.reason,
                          m.action_kind, m.action_note, c.grp AS cohort_group
                   FROM results r JOIN eval_rule_metadata m
                     ON m.run_id=r.run_id AND m.rule_id=r.rule_id AND m.rule_version=r.rule_version
                   JOIN cohort c ON c.run_id=r.run_id AND c.chr_id=r.chr_id AND c.grp='active'
                   WHERE r.run_id=? ORDER BY r.rule_id, r.chr_id""", (run_id,),
            ))
            if not snapshots or count != expected or len(rows) != count:
                raise ReportError("Run results or rule snapshots are incomplete; re-evaluate.")
            if any(r["state"] not in State._value2member_map_ for r in rows):
                raise ReportError("Run contains an unsupported result state.")
            return Run(run_id, date.fromisoformat(meta["as_of"]), meta["ruleset"], rows, cohort)
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError) as error:
        if isinstance(error, ReportError):
            raise
        raise ReportError("Couldn't read a complete ledger run; check the local store.") from None
