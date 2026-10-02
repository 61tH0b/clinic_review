"""Local files only, with HTML escaping and spreadsheet-safe CSV cells."""
from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path

from .data import ReportError, Run
from .diff import DIFF_FIELDS, compare_runs
from .feedback import FEEDBACK_FIELDS
from .provenance import version_stamp
from .worklists import FIELDS, worklists

NOTICE = (
    "Shadow results are for clinician review, not authorization to recall, order, book, or message. "
    "Clinical sign-off and audit gates still apply. DISCUSS is pre-visit only. "
    "These files contain patient-level information and must stay in the local data account."
)
DIFF_NOTICE = (
    "Closed means the result left the open-state set; it doesn't prove completed care. "
    "Check both states and cohort groups. Added/removed means not evaluated on one side, "
    "never evidence of closure."
)


def _directory(path: str | Path) -> Path:
    path = Path(path).resolve()
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ReportError("Output must be outside Git checkouts, even ignored folders.")
    try:
        # Refuse reuse so a report can't silently overwrite a prior review or feedback.
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        path.chmod(0o700)
    except OSError:
        raise ReportError("Couldn't create a new private output folder; choose a fresh local folder.") from None
    return path


def _safe_csv(value: str) -> str:
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv(path: Path, fields, rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as fh:
        path.chmod(0o600)
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: _safe_csv(str(row.get(key, ""))) for key in fields} for row in rows)


def _table(fields, rows) -> str:
    header = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = "".join("<tr>" + "".join(
        f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields
    ) + "</tr>" for row in rows)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _html(path: Path, title: str, intro: str, sections) -> None:
    stamp = version_stamp()
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        f"<title>{html.escape(title)}</title>"
        '<style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse;font-size:13px}'
        'td,th{border:1px solid #bbb;padding:.5rem;text-align:left;vertical-align:top}'
        'th{background:#eee}p{max-width:80ch}section{overflow:auto;margin:2rem 0}</style>'
        f"</head><body><h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p>"
        f"<p>{html.escape(NOTICE)}</p><p>{html.escape(stamp)}; generated {generated}</p>"
    )
    for name, fields, rows in sections:
        doc += f"<section><h2>{html.escape(name)} ({len(rows)})</h2>" + _table(fields, rows) + "</section>"
    doc += "</body></html>"
    with path.open("x", encoding="utf-8") as fh:
        path.chmod(0o600)
        fh.write(doc)


def write_worklists(run: Run, output: str | Path) -> dict[str, int]:
    lists = worklists(run)
    directory = _directory(output)
    try:
        for name, rows in lists.items():
            _csv(directory / f"{name}.csv", FIELDS, rows)
        template = [
            {**{key: row[key] for key in FEEDBACK_FIELDS[:3]}, "outcome": "", "date": "", "evidence_note": ""}
            for name, rows in lists.items() if name != "outreach" for row in rows
        ]
        _csv(directory / "feedback.csv", FEEDBACK_FIELDS, template)
        _html(directory / "worklists.html", "Screening review worklists",
              f"Run {run.run_id}; as of {run.as_of}; ruleset {run.ruleset}. "
              "Feedback is capture only; attestation validity remains undecided.",
              [(name, FIELDS, rows) for name, rows in lists.items()])
    except OSError:
        raise ReportError("Export failed; partial files may remain in the chosen local folder.") from None
    return {name: len(rows) for name, rows in lists.items()}


def write_diff(before: Run, after: Run, output: str | Path) -> dict[str, dict[str, int]]:
    diff = compare_runs(before, after)
    directory = _directory(output)
    warning = "Runs used different ruleset digests." if diff.ruleset_changed else "Ruleset digests match."
    try:
        _csv(directory / "diff.csv", DIFF_FIELDS, diff.rows)
        _html(directory / "diff.html", "Screening run diff",
              f"Before {before.run_id} ({before.as_of}, {before.ruleset}); "
              f"after {after.run_id} ({after.as_of}, {after.ruleset}). {warning} {DIFF_NOTICE}",
              [("rule results", DIFF_FIELDS, diff.rows)])
    except OSError:
        raise ReportError("Export failed; partial files may remain in the chosen local folder.") from None
    return diff.counts
