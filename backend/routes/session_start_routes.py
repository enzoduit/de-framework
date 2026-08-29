"""
Session Start Routes — POST /de/<name>/sessions/start and POST /de-start (local shorthand)
"""

import json
import uuid
import datetime
import subprocess as _sp
from backend.config import AGENTS_BASE, now_iso


def handle_session_start(handler, de_name, body):
    """POST /de/<name>/sessions/start — create and launch a new DE session."""
    de_json_file = AGENTS_BASE / de_name / 'de.json'
    if not de_json_file.exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})

    trigger_context = body.get('trigger_context', 'Manual start')
    trigger_type = body.get('trigger_type', 'user')

    # Generate session ID
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    short = uuid.uuid4().hex[:6]
    session_id = f'ws-{de_name}-{ts}-{short}'

    # Create session file
    sessions_dir = AGENTS_BASE / de_name / 'sessions'
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_data = {
        'id': session_id,
        'de': de_name,
        'trigger_type': trigger_type,
        'trigger_from': 'portal',
        'trigger_context': trigger_context,
        'status': 'queued',
        'decision_ids': [],
        'colleague_calls': {},
        'steps': [],
        'paused_state': None,
        'created_at': now_iso(),
        'updated_at': now_iso(),
        'summary': None,
    }
    (sessions_dir / f'{session_id}.json').write_text(json.dumps(session_data, indent=2))

    # Write trigger to inbox.jsonl
    inbox_file = AGENTS_BASE / de_name / 'inbox.jsonl'
    inbox_entry = {
        'type': 'manual_trigger',
        'session_id': session_id,
        'context': trigger_context,
        'trigger_type': trigger_type,
        'ts': now_iso(),
    }
    with open(inbox_file, 'a') as f:
        f.write(json.dumps(inbox_entry) + '\n')

    # Spawn session_runner.py in background
    _log = f'/tmp/session-{de_name}-{session_id}.log'
    _sp.Popen(
        ['python3', str(AGENTS_BASE / 'session_runner.py'), de_name, session_id],
        stdout=open(_log, 'w'),
        stderr=_sp.STDOUT,
        cwd=str(AGENTS_BASE),
    )

    return handler.send_json(200, {'ok': True, 'session_id': session_id})


def handle_de_start(handler, body):
    """POST /de-start — shorthand for local dev (portal calls this; Cloudflare proxies to /de/<name>/sessions/start).

    Accepts body: {de_name, trigger_type, trigger_context}
    """
    de_name = body.get('de_name')
    if not de_name:
        return handler.send_json(400, {'error': 'missing de_name'})

    return handle_session_start(handler, de_name, body)
