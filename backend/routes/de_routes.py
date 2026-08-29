"""
DE Routes — /de-list, /de/<name>, /de/<name>/sessions, /de/<name>/sessions/<id>
"""

import json
from pathlib import Path
from backend.config import AGENTS_BASE, DE_NAMES, now_iso


def _discover_de_names():
    """Discover DE names by scanning AGENTS_DIR for de.json files."""
    names = []
    if not AGENTS_BASE.exists():
        return names
    for d in sorted(AGENTS_BASE.iterdir()):
        if d.is_dir() and (d / 'de.json').exists():
            names.append(d.name)
    return names


def _get_de_names():
    """Return the list of DE names to use (configured or discovered)."""
    if DE_NAMES is not None:
        return DE_NAMES
    return _discover_de_names()


def _de_sessions_list(de_name, limit=50):
    sessions_dir = AGENTS_BASE / de_name / 'sessions'
    if not sessions_dir.exists():
        return []
    sessions = []
    for f in sorted(sessions_dir.glob('*.json'), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
            sessions.append({
                'id': d.get('id'),
                'status': d.get('status'),
                'trigger_type': d.get('trigger_type'),
                'trigger_context': (d.get('trigger_context') or '')[:100],
                'created_at': d.get('created_at'),
                'updated_at': d.get('updated_at'),
                'step_count': len(d.get('steps', [])),
                'summary': d.get('summary'),
            })
        except Exception:
            pass
    return sessions


def _de_session_count(de_name):
    sessions_dir = AGENTS_BASE / de_name / 'sessions'
    if not sessions_dir.exists():
        return 0
    return len(list(sessions_dir.glob('*.json')))


def _de_pending_count(de_name):
    decisions_file = AGENTS_BASE / de_name / 'decisions.json'
    if not decisions_file.exists():
        return 0
    try:
        d = json.loads(decisions_file.read_text())
        return len(d.get('pending', []))
    except Exception:
        return 0


def handle_de_list(handler):
    """GET /de-list — list all Digital Employees with summary info."""
    de_names = _get_de_names()
    des = []
    for de_name in de_names:
        de_json_file = AGENTS_BASE / de_name / 'de.json'
        if not de_json_file.exists():
            continue
        try:
            d = json.loads(de_json_file.read_text())
            sessions = _de_sessions_list(de_name, limit=1)
            last_session = sessions[0] if sessions else None
            des.append({
                'name': d.get('name'),
                'display_name': d.get('display_name'),
                'role': d.get('role'),
                'color': d.get('color'),
                'mission': d.get('mission', '')[:200],
                'pending_decisions': _de_pending_count(de_name),
                'last_session': last_session,
                'session_count': _de_session_count(de_name),
            })
        except Exception as e:
            des.append({'name': de_name, 'error': str(e)})
    return handler.send_json(200, {'des': des, 'ts': now_iso()})


def handle_de_get(handler, parts):
    """Handle GET /de/<name>[/sessions[/<session_id>][/workspace[/<filename>]]]"""
    # parts = ['de', ...]
    if len(parts) == 1:
        return handler.send_json(400, {'error': 'missing DE name'})

    de_name = parts[1]
    de_dir = AGENTS_BASE / de_name
    de_json_file = de_dir / 'de.json'

    if not de_json_file.exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})

    de_data = json.loads(de_json_file.read_text())

    # GET /de/<name>  — full DE detail
    if len(parts) == 2:
        sessions = _de_sessions_list(de_name, limit=20)
        pending = _de_pending_count(de_name)
        return handler.send_json(200, {
            **de_data,
            'pending_decisions': pending,
            'sessions': sessions,
            'session_count': _de_session_count(de_name),
        })

    # GET /de/<name>/sessions  — session list
    if len(parts) == 3 and parts[2] == 'sessions':
        sessions = _de_sessions_list(de_name, limit=50)
        return handler.send_json(200, {'sessions': sessions, 'count': len(sessions)})

    # GET /de/<name>/sessions/<session_id>  — full session detail
    if len(parts) == 4 and parts[2] == 'sessions':
        session_id = parts[3]
        session_file = de_dir / 'sessions' / f'{session_id}.json'
        if not session_file.exists():
            return handler.send_json(404, {'error': f'Session not found: {session_id}'})
        session_data = json.loads(session_file.read_text())
        return handler.send_json(200, session_data)

    # GET /de/<name>/workspace  — list workspace files
    if len(parts) == 3 and parts[2] == 'workspace':
        ws_dir = de_dir / 'workspace'
        ws_dir.mkdir(parents=True, exist_ok=True)
        import datetime as _dt
        files = []
        for f in sorted(ws_dir.iterdir()):
            if f.is_file() and not f.name.startswith('.'):
                stat = f.stat()
                files.append({
                    'name': f.name,
                    'size_kb': round(stat.st_size / 1024, 1),
                    'modified': _dt.datetime.fromtimestamp(
                        stat.st_mtime, tz=_dt.timezone.utc
                    ).strftime('%Y-%m-%d %H:%M'),
                })
        return handler.send_json(200, {'files': files, 'count': len(files), 'de': de_name})

    # GET /de/<name>/workspace/<filename>  — read file content for popup viewer
    if len(parts) == 4 and parts[2] == 'workspace':
        filename = parts[3]
        ws_dir = de_dir / 'workspace'
        fp = ws_dir / filename
        if not fp.exists() or not fp.is_file():
            return handler.send_json(404, {'error': 'File not found'})
        if not str(fp.resolve()).startswith(str(ws_dir.resolve())):
            return handler.send_json(403, {'error': 'Access denied'})
        try:
            content = fp.read_text(encoding='utf-8', errors='replace')
            binary = False
        except Exception:
            content = '[Binary file — cannot preview]'
            binary = True
        return handler.send_json(200, {
            'filename': filename,
            'content': content,
            'size_kb': round(fp.stat().st_size / 1024, 1),
            'binary': binary,
        })

    return handler.send_json(404, {'error': 'not found'})
