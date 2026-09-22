#!/usr/bin/env python3
"""
Krisp Webhook Proxy — port 8770
Handles: /hooks/krisp, /hooks/lead, /wa, /augedo-launch

Recreated 2026-09-22 from nginx config + memory context.
Original purpose: receive Krisp meeting webhooks, save JSON to context/meetings/,
and handle lead/WhatsApp/Augedo-launch webhooks.
"""
import json
import os
import re
import datetime
import pathlib
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

MEETINGS_DIR = pathlib.Path("/root/.openclaw/workspace/context/meetings")
LEADS_DIR = pathlib.Path("/root/.openclaw/workspace/context/leads")
HOOKS_LOG = pathlib.Path("/root/.openclaw/workspace/context/hooks.log")

MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
LEADS_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60]


def log(msg: str):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {msg}"
    print(line)
    try:
        with open(HOOKS_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence default HTTP logging

    def send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw.decode("utf-8", errors="replace")}

    def do_GET(self):
        if self.path in ("/health", "/"):
            self.send_json(200, {"ok": True, "service": "krisp-proxy"})
        else:
            self.send_json(404, {"ok": False})

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/hooks/krisp":
            self.handle_krisp()
        elif path == "/hooks/lead":
            self.handle_lead()
        elif path == "/wa":
            self.handle_wa()
        elif path == "/augedo-launch":
            self.handle_augedo_launch()
        else:
            log(f"UNKNOWN POST {path}")
            self.send_json(404, {"ok": False, "error": "unknown route"})

    def handle_krisp(self):
        """Receive Krisp meeting webhook, save JSON to context/meetings/."""
        payload = self.read_body()
        try:
            # Extract meeting date + title for filename
            date_str = None
            title = "meeting"

            # Krisp sends various formats — try common fields
            if "date" in payload:
                date_str = payload["date"][:10]
            elif "startTime" in payload:
                date_str = payload["startTime"][:10]
            elif "created_at" in payload:
                date_str = payload["created_at"][:10]

            if not date_str:
                date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

            if "title" in payload:
                title = slugify(payload["title"])
            elif "meeting_name" in payload:
                title = slugify(payload["meeting_name"])
            elif "name" in payload:
                title = slugify(payload["name"])

            filename = f"{date_str}-{title}.json"
            out_path = MEETINGS_DIR / filename

            # Avoid duplicates by appending suffix
            if out_path.exists():
                suffix = datetime.datetime.utcnow().strftime("%H%M%S")
                filename = f"{date_str}-{title}-{suffix}.json"
                out_path = MEETINGS_DIR / filename

            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            log(f"KRISP saved {filename} ({len(payload)} keys)")
            self.send_json(200, {"ok": True, "saved": filename})

        except Exception as e:
            log(f"KRISP error: {e}")
            self.send_json(500, {"ok": False, "error": str(e)})

    def handle_lead(self):
        """Receive lead webhook, save to context/leads/."""
        payload = self.read_body()
        try:
            ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            source = payload.get("source", "unknown")
            filename = f"{ts}-{slugify(source)}.json"
            out_path = LEADS_DIR / filename
            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            log(f"LEAD saved {filename}")
            self.send_json(200, {"ok": True, "saved": filename})
        except Exception as e:
            log(f"LEAD error: {e}")
            self.send_json(500, {"ok": False, "error": str(e)})

    def handle_wa(self):
        """WhatsApp webhook — log and acknowledge."""
        payload = self.read_body()
        try:
            ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            log(f"WA {ts} keys={list(payload.keys())[:5]}")
            # WhatsApp challenge verification
            if "hub.challenge" in self.path:
                challenge = self.path.split("hub.challenge=")[-1].split("&")[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(challenge.encode())
                return
            self.send_json(200, {"ok": True})
        except Exception as e:
            log(f"WA error: {e}")
            self.send_json(500, {"ok": False, "error": str(e)})

    def handle_augedo_launch(self):
        """Augedo launch webhook — log and acknowledge."""
        payload = self.read_body()
        try:
            ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            log(f"AUGEDO-LAUNCH {ts} keys={list(payload.keys())[:5]}")
            self.send_json(200, {"ok": True})
        except Exception as e:
            log(f"AUGEDO-LAUNCH error: {e}")
            self.send_json(500, {"ok": False, "error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("KRISP_PROXY_PORT", 8770))
    log(f"krisp-proxy starting on :{port}")
    server = HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("krisp-proxy stopped")
