"""
Workspace Routes — /de/<name>/workspace/upload[/<filename>] (POST)
GET / text-write / delete workspace routes are handled in de_routes.py
"""

import json
import cgi
import os.path as _osp
import subprocess
from pathlib import Path as _Path
from backend.config import AGENTS_BASE


def _try_extract_text(file_path: _Path, ws_dir: _Path):
    """Auto-extract text from binary files to a sidecar .txt file after upload.
    Supports: PDF (pdftotext), DOCX (python-docx), XLSX/XLS (openpyxl/csv).
    Text-based files (csv, json, txt, md, py, etc.) need no extraction.
    Returns the .txt path on success, None if extraction not applicable/failed.
    """
    ext = file_path.suffix.lower()
    txt_path = ws_dir / (file_path.stem + '.txt')

    try:
        if ext == '.pdf':
            result = subprocess.run(
                ['pdftotext', str(file_path), str(txt_path)],
                capture_output=True, timeout=30
            )
            if result.returncode == 0 and txt_path.exists() and txt_path.stat().st_size > 0:
                return txt_path

        elif ext in ('.docx', '.doc'):
            import docx as _docx
            doc = _docx.Document(str(file_path))
            text = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
            if text:
                txt_path.write_text(text, encoding='utf-8')
                return txt_path

        elif ext in ('.xlsx', '.xls', '.ods'):
            import openpyxl as _xl
            import csv as _csv, io as _io
            wb = _xl.load_workbook(str(file_path), read_only=True, data_only=True)
            buf = _io.StringIO()
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                buf.write(f'# Sheet: {sheet}\n')
                writer = _csv.writer(buf)
                for row in ws.iter_rows(values_only=True):
                    writer.writerow([str(c) if c is not None else '' for c in row])
                buf.write('\n')
            text = buf.getvalue()
            if text.strip():
                txt_path.write_text(text, encoding='utf-8')
                return txt_path

    except Exception:
        pass
    return None


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
            extra = {}
            if dest.suffix.lower() in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.ods'):
                txt = _try_extract_text(dest, ws_dir)
                if txt:
                    extra['extracted_text'] = txt.name
            return handler.send_json(200, {'ok': True, 'name': safe, 'size': len(data), **extra})
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
