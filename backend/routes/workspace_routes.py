"""
Workspace Routes — /de/<name>/workspace/upload (POST)
GET workspace routes are handled in de_routes.py
"""

import json
import cgi
import os.path as _osp
from backend.config import AGENTS_BASE


def handle_upload(handler, parts):
    """POST /de/<name>/workspace/upload — upload a file to DE workspace."""
    # parts = ['de', '<name>', 'workspace', 'upload']
    if len(parts) != 4 or parts[0] != 'de' or parts[2] != 'workspace' or parts[3] != 'upload':
        return handler.send_json(400, {'error': 'invalid upload path'})

    de_name = parts[1]
    ct = handler.headers.get('Content-Type', '')
    if 'multipart' not in ct:
        return handler.send_json(400, {'error': 'multipart required'})

    try:
        form = cgi.FieldStorage(
            fp=handler.rfile,
            headers=handler.headers,
            environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': ct},
        )
        if 'file' not in form:
            return handler.send_json(400, {'error': 'no file field'})

        fi = form['file']
        safe = _osp.basename(fi.filename.replace('..', ''))
        if not safe:
            return handler.send_json(400, {'error': 'invalid filename'})

        ws_dir = AGENTS_BASE / de_name / 'workspace'
        ws_dir.mkdir(parents=True, exist_ok=True)
        dest = ws_dir / safe
        dest.write_bytes(fi.file.read())

        return handler.send_json(200, {'ok': True, 'filename': safe})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})
