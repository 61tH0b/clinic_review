"""Source provenance for local reports; no deployment is implied."""
from __future__ import annotations

import subprocess
from pathlib import Path

VERSION = "0.2.0"


def version_stamp() -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%h %cI"], cwd=root,
            capture_output=True, text=True, timeout=2, check=True,
        )
        source = proc.stdout.strip() or "source unknown"
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, timeout=2, check=True)
        if dirty.stdout:
            source += " (local changes)"
    except (OSError, subprocess.SubprocessError):
        source = "source unknown"
    return f"clinic-review-report {VERSION}; source {source}"
