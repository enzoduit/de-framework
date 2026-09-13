"""
Workspace Routes — /de/<name>/workspace/upload[/<filename>] (POST)
GET / text-write / delete workspace routes are handled in de_routes.py
"""

import json
import cgi
import os.path as _osp
from backend.config import AGENTS_BASE


def handle_upload(handler, parts):
    """POST /de/<name>/workspace/upload[/<filename>] — upload a file to DE workspace.

    Supports two forms:
      - 4-part path (legacy): /de/<name>/workspace/upload  — multipart only
      - 5-part path (new):    /de/<name>/workspace/upload/<filename>  — raw body or multipart
    """
    # parts = ['de', '<name>', 'workspace', 'upload'] or
    #         ['de', '<name>', 'workspace', 'upload', '<filename>']
    if len(parts) not in (4, 5) or parts[0] != 'de' or parts[2] != 'workspace' or parts[3] != 'upload':
        return handler.send_json(400, {'error': 'invalid upload path'})

    de_name = parts[1]
    url_filename = parts[4] if len(parts) == 5 else None

    ct = handler.headers.get('Content-Type', '')
    ws_dir = AGENTS_BASE / de_name / 'workspace'
    ws_dir.mkdir(parents=True, exist_ok=True)

    try:
        if 'multipart' in ct:
            # Multipart form upload
            form = cgi.FieldStorage(
                fp=handler.rfile,
                headers=handler.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': ct},
            )
            if 'file' not in form:
                return handler.send_json(400, {'error': 'no file field'})
            fi = form['file']
            raw_name = url_filename or (fi.filename if fi.filename else '')
            safe = _osp.basename(raw_name.replace('..', ''))
            if not safe:
                return handler.send_json(400, {'error': 'invalid filename'})
            dest = ws_dir / safe
            data = fi.file.read()
            dest.write_bytes(data)
            return handler.send_json(200, {'ok': True, 'name': safe, 'size': len(data)})
        else:
            # Raw body upload — filename must come from URL
            if not url_filename:
                return handler.send_json(400, {'error': 'filename required in URL for raw body upload'})
            safe = _osp.basename(url_filename.replace('..', ''))
            if not safe:
                return handler.send_json(400, {'error': 'invalid filename'})
            length = int(handler.headers.get('Content-Length', 0))
            data = handler.rfile.read(length) if length else b''
            dest = ws_dir / safe
            dest.write_bytes(data)
            return handler.send_json(200, {'ok': True, 'name': safe, 'size': len(data)})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})
