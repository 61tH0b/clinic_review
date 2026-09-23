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
PATIENT_IDS = ["1001", "1002", "1003", "1004", "1005", "1006"]
CANARY_ID = "5000"
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
                m = re.fullmatch(r"/api/patients/([^/]+)", path)
                if m:
                    pid = m.group(1)
                    return self._json(
                        {"patient_id": pid, "status": "active", "sex": "F", "dob": "1970-01-01", "primary_provider": "Dr Synthetic"}
                    )
                m = re.fullmatch(r"/api/patients/([^/]+)/labs", path)
                if m:
                    pid = m.group(1)
                    if emr.state["hang_labs"] == pid:
                        time.sleep(emr.state["hang_seconds"])
                    shown = "7777" if emr.state["wrong_patient"] == pid else pid
                    return self._json(
                        {"patient_id": shown, "results": [{"id": "L1", "name": "HbA1c", "value": "6.1", "patient_id": shown}]}
                    )
                m = re.fullmatch(r"/api/patients/([^/]+)/files", path)
                if m:
                    pid = m.group(1)
                    return self._json({"patient_id": pid, "files": [{"file_id": f"F{pid}A", "tag": "Diagnostic Imaging"}]})
                if re.fullmatch(r"/api/files/[^/]+/content", path):
                    return self._send(200, FAKE_PDF, "application/pdf")
                return self._json({"error": "not found"}, 404)

        return Handler
