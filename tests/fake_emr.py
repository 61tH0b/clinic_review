"""A fake EMR server for walker tests. Synthetic patients only.

Behaviour switches live in `state` so a test can flip them mid-run:
  logged_out       every /api/ call returns 401, and the app sends the page to /login
  wrong_patient    labs for this patient id come back labelled as another patient
  hang_labs        labs for this patient id take longer than the screen timeout
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).parent / "fixtures" / "fake_emr" / "static"
CANARY_ID = "5000"


def _lab(lid, name, value, collected):
    return {"id": lid, "name": name, "value": value, "collected": collected}


def _file(fid, tag, title, on):
    return {"file_id": fid, "tag": tag, "title": title, "date": on}


# Synthetic charts. Each one exercises a different path through cohort and rules; the
# pipeline test spells out what each should come to on 2026-10-02.
CHARTS = {
    "1001": {  # 58 F, diabetic, everything up to date except cervix; no smoking status
        "summary": {"status": "active", "sex": "F", "dob": "1968-04-02", "last_visit": "2026-08-01"},
        "problems": [{"id": "P1", "description": "Type 2 diabetes", "icd9": "250", "onset": "2015-03-01"}],
        "medications": [{"id": "M1", "name": "Metformin", "sig": "500 mg BID"}],
        "labs": [_lab("L1", "HbA1c", "7.1", "2026-07-01"), _lab("L2", "FIT", "Negative", "2025-06-10")],
        "files": [
            _file("F1001A", "Consults", "Diabetic eye exam - optometry", "2026-03-20"),
            _file("F1001B", "Diagnostic Imaging", "Screening Mammogram Bilateral", "2025-02-01"),
        ],
    },
    "1002": {  # 67 M ex-smoker with a positive FIT and no colonoscopy report
        "summary": {"status": "active", "sex": "M", "dob": "1958-11-20", "last_visit": "2025-12-01"},
        "problems": [
            {"id": "P1", "description": "Ex-smoker, quit 2010", "icd9": "", "onset": ""},
            {"id": "P2", "description": "Hypertension", "icd9": "401", "onset": "2012-01-01"},
        ],
        "medications": [{"id": "M1", "name": "Atorvastatin", "sig": "20 mg daily"}],
        "labs": [_lab("L1", "FIT", "Positive", "2026-03-01")],
        "files": [],
    },
    "1003": {  # 36 F on adalimumab: follows the immunocompromised cervix rule instead
        "summary": {"status": "active", "sex": "F", "dob": "1990-05-05", "last_visit": "2026-09-01"},
        "problems": [{"id": "P1", "description": "Seasonal allergies", "icd9": "", "onset": ""}],
        "medications": [{"id": "M1", "name": "Humira", "sig": "40 mg SC q2w"}],
        "labs": [_lab("L1", "HbA1c", "5.4", "2026-01-10"), _lab("L2", "HPV", "Not Detected", "2023-04-01")],
        "files": [_file("F1003A", "Diagnostic Imaging", "Pelvic ultrasound", "2025-05-05")],
    },
    "1004": {  # not seen in 36 months: outreach list, no rules
        "summary": {"status": "active", "sex": "F", "dob": "1975-08-08", "last_visit": "2020-01-15"},
        "problems": [],
        "medications": [],
        "labs": [_lab("L1", "HbA1c", "6.1", "2019-12-01")],
        "files": [],
    },
    "1005": {  # inactive: excluded
        "summary": {"status": "inactive", "sex": "M", "dob": "1980-02-02", "last_visit": "2026-01-01"},
        "problems": [],
        "medications": [],
        "labs": [],
        "files": [],
    },
    "1006": {  # 76 F, diabetic, last retinal exam 2024: overdue past the grace year
        "summary": {"status": "active", "sex": "F", "dob": "1950-01-15", "last_visit": "2026-05-01"},
        "problems": [
            {"id": "P1", "description": "DM2", "icd9": "", "onset": ""},
            {"id": "P2", "description": "TAH-BSO 2009", "icd9": "", "onset": "2009-05-04"},
        ],
        "medications": [],
        "labs": [],
        "files": [_file("F1006A", "Consults", "Retinal exam", "2024-06-01")],
    },
    CANARY_ID: {
        "summary": {"status": "active", "sex": "F", "dob": "1970-01-01", "last_visit": "2026-01-01"},
        "problems": [],
        "medications": [],
        "labs": [_lab("L1", "HbA1c", "5.0", "2026-01-01")],
        "files": [],
    },
}
PATIENT_IDS = [pid for pid in CHARTS if pid != CANARY_ID]
PAGE_SIZE = 2
FAKE_PDF = b"%PDF-1.4\n% synthetic test document\n%%EOF\n"


class FakeEMR:
    def __init__(self) -> None:
        self.state: dict = {"logged_out": False, "wrong_patient": None, "hang_labs": None, "hang_seconds": 5}
        self.requests: list[str] = []
        handler = self._handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeEMR":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(self):
        emr = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, doc, status: int = 200) -> None:
                self._send(status, json.dumps(doc).encode(), "application/json; charset=utf-8")

            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                path = parts.path
                emr.requests.append(self.path)
                if path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
                if path == "/app.js":
                    return self._send(200, (STATIC / "app.js").read_bytes(), "application/javascript")
                if path == "/login":
                    return self._send(200, (STATIC / "login.html").read_bytes(), "text/html")
                if not path.startswith("/api/"):
                    return self._send(404, b"not found", "text/plain")
                if emr.state["logged_out"]:
                    return self._json({"error": "unauthorized"}, 401)
                if path == "/api/notifications":
                    return self._json({"count": 3})
                if path == "/api/patients":
                    page = int(parse_qs(parts.query).get("page", ["1"])[0])
                    chunk = PATIENT_IDS[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
                    return self._json({"page": page, "items": [{"id": pid, "name": f"Synthetic {pid}"} for pid in chunk]})
                m = re.fullmatch(r"/api/patients/([^/]+)(/[a-z]+)?", path)
                if m and m.group(1) in CHARTS:
                    pid, sub = m.group(1), (m.group(2) or "/summary")[1:]
                    chart = CHARTS[pid]
                    if sub == "summary":
                        return self._json({"patient_id": pid, "primary_provider": "Dr Synthetic", **chart["summary"]})
                    if sub == "labs":
                        if emr.state["hang_labs"] == pid:
                            time.sleep(emr.state["hang_seconds"])
                        shown = "7777" if emr.state["wrong_patient"] == pid else pid
                        rows = [{**r, "patient_id": shown} for r in chart["labs"]]
                        return self._json({"patient_id": shown, "results": rows})
                    if sub in ("problems", "medications", "files"):
                        return self._json({"patient_id": pid, sub: chart[sub]})
                if re.fullmatch(r"/api/files/[^/]+/content", path):
                    return self._send(200, FAKE_PDF, "application/pdf")
                return self._json({"error": "not found"}, 404)

        return Handler
