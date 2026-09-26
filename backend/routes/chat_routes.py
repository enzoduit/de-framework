"""
Chat Routes — POST /chat/<de_name>
Direct human → DE message that saves input and spawns a session.
"""

import json
import uuid
import datetime
import subprocess as _sp
from pathlib import Path
from backend.config import AGENTS_BASE, now_iso

_BACKEND_DIR = Path(__file__).parent.parent
_SESSION_RUNNER = _BACKEND_DIR / 'core' / 'session_runner.py'


def handle_chat(handler, de_name: str, body: dict):
    """POST /chat/<de_name> — send a message directly to a DE.

    Body: { "message": "...", "user": "human" }
    Response: { "session_id": "ws-...", "status": "triggered" }
    """
    message = (body.get('message') or '').strip()
    user = body.get('user', 'human')

    if not message:
        return handler.send_json(400, {'error': 'message is required'})

    de_dir = AGENTS_BASE / de_name
    if not (de_dir / 'de.json').exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})

    # ── Save user input (P1) ──────────────────────────────────────────────
    try:
        ui_dir = de_dir / 'user_inputs'
        ui_dir.mkdir(parents=True, exist_ok=True)
        ts_label = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-%H-%M')
        (ui_dir / f'{ts_label}-chat.json').write_text(json.dumps({
            'timestamp': now_iso(),
            'type': 'chat',
            'de': de_name,
            'user': user,
            'message': message,
        }, indent=2))
    except Exception:
        pass  # Never fail the session start because of input logging

    # ── Create session file ───────────────────────────────────────────────
    ts2 = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    short = uuid.uuid4().hex[:6]
    session_id = f'ws-{de_name}-{ts2}-{short}'

    sessions_dir = de_dir / 'sessions'
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_data = {
        'id': session_id,
        'de': de_name,
        'trigger_type': 'user',
        'trigger_from': 'portal_chat',
        'trigger_context': f'[Message from {user} via portal chat] {message}',
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

    # ── Spawn session runner ──────────────────────────────────────────────
    try:
        rlog = f'/tmp/chat-{de_name}-{session_id}.log'
        _sp.Popen(
            ['python3', str(_SESSION_RUNNER), de_name, session_id],
            stdout=open(rlog, 'w'), stderr=_sp.STDOUT,
            cwd=str(AGENTS_BASE),
        )
    except Exception as e:
        return handler.send_json(500, {'error': f'Failed to start session: {e}'})

    return handler.send_json(200, {'session_id': session_id, 'status': 'triggered'})
