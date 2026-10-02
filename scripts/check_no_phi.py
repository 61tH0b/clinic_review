#!/usr/bin/env python3
"""Keep patient data out of git.

Fails if a checked file contains a number that passes the BC PHN check
(10 digits, leading 9, mod-11 check digit), or if a data-type file is
being committed. Synthetic fixtures must use PHNs that fail the check.

    scripts/check_no_phi.py          # staged files (pre-commit hook)
    scripts/check_no_phi.py --all    # every tracked file (CI)
"""
import re
import subprocess
import sys
from pathlib import PurePosixPath

PHN_WEIGHTS = (2, 4, 8, 5, 10, 9, 7, 3)
PHN_LIKE = re.compile(r"(?<!\d)9\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)")
DATA_SUFFIXES = {
    ".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".sqlite", ".db",
    ".pdf", ".hl7", ".ndjson", ".har", ".zip",
}
DATA_OK_UNDER = ("tests/fixtures/",)


def is_bc_phn(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit() or digits[0] != "9":
        return False
    total = sum(int(d) * w for d, w in zip(digits[1:9], PHN_WEIGHTS))
    check = 11 - (total % 11)
    return check < 10 and check == int(digits[9])


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def files_to_check(all_files: bool) -> list[str]:
    if all_files:
        return [f for f in git("ls-files").splitlines() if f]
    return [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if f]


def read(path: str, all_files: bool) -> str:
    if all_files:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", errors="ignore")
    blob = subprocess.run(["git", "show", f":{path}"], check=True, capture_output=True).stdout
    return blob.decode("utf-8", errors="ignore")


def main() -> int:
    all_files = "--all" in sys.argv[1:]
    problems = []
    for path in files_to_check(all_files):
        if path == "scripts/check_no_phi.py":
            continue
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in DATA_SUFFIXES and not path.startswith(DATA_OK_UNDER):
            problems.append(f"{path}: data file type {suffix} isn't allowed in this repo")
            continue
        for lineno, line in enumerate(read(path, all_files).splitlines(), 1):
            for match in PHN_LIKE.finditer(line):
                if is_bc_phn(re.sub(r"[ -]", "", match.group())):
                    problems.append(f"{path}:{lineno}: looks like a valid BC PHN")
    if problems:
        print("Blocked: possible patient data.\n  " + "\n  ".join(problems), file=sys.stderr)
        print("Nothing patient-level goes in this repo. Keep it on the clinic Mac.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
