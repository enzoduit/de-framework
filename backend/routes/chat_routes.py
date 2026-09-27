"""
Chat Routes — POST /chat/<de_name>

Persistent session architecture:
  - Each DE gets a fixed session key: agent:test-intern:chat-<de_name>
  - Messages are sent via `openclaw agent --session-key` (synchronous, ~5s)
  - No session spawning, no polling — response returned directly
  - Session key stored in de.json for reference/visibility

Response: { "response": str, "session_key": str, "status": "ok" }
"""

import json
import subprocess
import datetime
from pathlib import Path
from backend.config import AGENTS_BASE, now_iso

_BACKEND_DIR = Path(__file__).parent.parent
_SESSION_KEY_PREFIX = 'agent:test-intern:chat-'
_CHAT_TIMEOUT = 90  # seconds — openclaw agent subprocess timeout (heavy DEs can take 60s)


def _load_de(de_name: str) -> dict | None:
    de_file = AGENTS_BASE / de_name / 'de.json'
    if not de_file.exists():
        return None
    return json.loads(de_file.read_text())


def _save_de(de_name: str, de: dict) -> None:
    de_file = AGENTS_BASE / de_name / 'de.json'
    de_file.write_text(json.dumps(de, indent=2))


def _session_key(de_name: str) -> str:
    return f'{_SESSION_KEY_PREFIX}{de_name}'


def _build_message(de: dict, user_message: str) -> str:
    """
    Prepend a concise DE-context header so the persistent session
    knows who it is AND stays in fast chat mode (no unsolicited tool calls).
    """
    name = de.get('display_name', de.get('name', '').upper())
    role = de.get('role', 'Digital Employee')
    mission = de.get('mission', '')
    return (
        f'[CHAT MODE — You are {name}, Ed\'s {role}. '
        f'Mission: {mission}\n'
        f'RULES: Answer from memory. NO tool calls or file reads unless Ed explicitly asks. '
        f'Keep replies short (2-4 sentences max). Be direct and conversational.]\n\n'
        f'{user_message}'
    )


def _log_user_input(de_name: str, message: str, user: str) -> None:
    """Persist user input for audit/memory. Best-effort."""
    try:
        ui_dir = AGENTS_BASE / de_name / 'user_inputs'
        ui_dir.mkdir(parents=True, exist_ok=True)
        ts_label = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-%H-%M-%S')
        (ui_dir / f'{ts_label}-chat.json').write_text(json.dumps({
            'timestamp': now_iso(),
            'type': 'chat',
            'de': de_name,
            'user': user,
            'message': message,
        }, indent=2))
    except Exception:
        pass


def handle_chat(handler, de_name: str, body: dict):
    """POST /chat/<de_name> — send a message to a DE's persistent session.

    Body: { "message": str, "user": str? }
    Response (success): { "response": str, "session_key": str, "status": "ok" }
    Response (error): { "error": str }
    """
    message = (body.get('message') or '').strip()
    user = body.get('user', 'human')

    if not message:
        return handler.send_json(400, {'error': 'message is required'})

    de_dir = AGENTS_BASE / de_name
    if not (de_dir / 'de.json').exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})

    de = _load_de(de_name)
    session_key = _session_key(de_name)

    # Persist user input (audit trail — never blocks the response)
    _log_user_input(de_name, message, user)

    # Store session_key in de.json on first use (for visibility / portal link)
    if de.get('chat_session_key') != session_key:
        de['chat_session_key'] = session_key
        _save_de(de_name, de)

    full_message = _build_message(de, message)

    try:
        result = subprocess.run(
            [
                'openclaw', 'agent',
                '--agent', 'test-intern',
                '--session-key', session_key,
                '--message', full_message,
                '--json',
            ],
            capture_output=True,
            text=True,
            timeout=_CHAT_TIMEOUT,
        )

        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else '(no stderr)'
            return handler.send_json(500, {
                'error': 'Agent call failed',
                'detail': stderr,
                'session_key': session_key,
            })

        data = json.loads(result.stdout)
        payloads = data.get('result', {}).get('payloads', [])
        response_text = payloads[0].get('text', '') if payloads else '(no response)'
        duration_ms = data.get('result', {}).get('meta', {}).get('durationMs', 0)

        return handler.send_json(200, {
            'response': response_text,
            'session_key': session_key,
            'status': 'ok',
            'duration_ms': duration_ms,
        })

    except subprocess.TimeoutExpired:
        return handler.send_json(504, {
            'error': f'Agent timeout ({_CHAT_TIMEOUT}s) — DE may be busy',
            'session_key': session_key,
        })
    except json.JSONDecodeError as e:
        return handler.send_json(500, {
            'error': f'Invalid JSON from agent: {e}',
            'raw': result.stdout[:300] if result else '',
        })
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})
