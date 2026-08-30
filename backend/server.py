#!/usr/bin/env python3
"""
Digital Employees Framework — API Server
HTTP entry point. Delegates all routes to route modules.

Usage:
    python backend/server.py

Environment:
    See .env.example for required variables.
    Load with: source .env
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Allow imports from project root when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import AUTH_TOKEN, PORT
from backend.routes import (
    de_routes,
    decisions_routes,
    tasks_routes,
    workspace_routes,
    session_start_routes,
    system_routes,
    signup_routes,
    setup_routes,
)


class DEHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # quiet logging; remove this line to see access logs

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        origin = self.headers.get('Origin', '')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', origin or '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()

    def check_auth(self):
        auth = self.headers.get('Authorization', '')
        return auth == f'Bearer {AUTH_TOKEN}'

    def path_base(self):
        """Return path without query string."""
        return self.path.split('?')[0]

    def do_GET(self):
        path = self.path_base()
        parts = [p for p in path.split('/') if p]

        # ── Public GET endpoints (no auth) ─────────────────────────────────
        if path == '/health':
            return self.send_json(200, {'status': 'ok'})

        if path == '/pageviews':
            return system_routes.handle_pageviews(self)

        # ── Auth required for all remaining GET ─────────────────────────────
        if not self.check_auth():
            return self.send_json(401, {'error': 'unauthorized'})

        if path == '/de-list':
            return de_routes.handle_de_list(self)

        if parts and parts[0] == 'de':
            return de_routes.handle_de_get(self, parts)

        if path == '/decisions':
            return decisions_routes.handle_decisions_get(self)

        if path == '/audit-log':
            return decisions_routes.handle_audit_log_get(self)

        if path == '/agents-data':
            return system_routes.handle_agents_data(self)

        if path == '/system-data':
            return system_routes.handle_system_data(self)

        if path == '/settings-data':
            return system_routes.handle_settings_data(self)

        if path == '/tasks':
            return tasks_routes.handle_tasks_get(self)

        if path == '/signup-list':
            return signup_routes.handle_signup_list(self)

        self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path_base()
        parts = [p for p in path.split('/') if p]

        # ── Workspace upload — multipart, must handle before JSON body read ─
        if '/workspace/upload' in path:
            if not self.check_auth():
                return self.send_json(401, {'error': 'unauthorized'})
            return workspace_routes.handle_upload(self, parts)

        # ── Read JSON body once (shared by all remaining POST handlers) ──────
        length = int(self.headers.get('Content-Length', 0))
        body = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                body = {}

        # ── Public POST endpoints (no auth required) ─────────────────────────
        if path == '/signup':
            return signup_routes.handle_signup(self, body)

        if path == '/collab':
            return signup_routes.handle_collab(self, body)

        if path == '/pageview':
            return system_routes.handle_pageview(self, body)

        if path == '/leads':
            return signup_routes.handle_leads(self, body)

        # ── Auth required for remaining POST ─────────────────────────────────
        if not self.check_auth():
            return self.send_json(401, {'error': 'unauthorized'})

        if path == '/decide':
            return decisions_routes.handle_decide(self, body)

        if path == '/audit-log':
            return decisions_routes.handle_audit_log_post(self, body)

        if path == '/task-done':
            return tasks_routes.handle_task_done(self, body)

        if path == '/revert':
            return decisions_routes.handle_revert(self, body)

        if path == '/update-voice-prompt':
            return system_routes.handle_update_voice_prompt(self, body)

        # ── Session start: /de/<name>/sessions/start ──────────────────────────
        if (len(parts) == 4 and parts[0] == 'de'
                and parts[2] == 'sessions' and parts[3] == 'start'):
            return session_start_routes.handle_session_start(self, parts[1], body)

        # ── /de-start — local-dev shorthand (Cloudflare proxies this in production)
        if path == '/de-start':
            return session_start_routes.handle_de_start(self, body)

        if path == '/de/create':
            return de_routes.handle_de_create(self, body)

        if path == '/de/setup-chat':
            return setup_routes.handle_setup_chat(self, body)

        self.send_json(404, {'error': 'not found'})


def run():
    import socketserver

    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True

    server = ReusableHTTPServer(('0.0.0.0', PORT), DEHandler)
    print(f'[DE Framework API] Running on port {PORT}')
    print(f'[DE Framework API] AGENTS_DIR: {__import__("backend.config", fromlist=["AGENTS_BASE"]).AGENTS_BASE}')
    server.serve_forever()


if __name__ == '__main__':
    run()
