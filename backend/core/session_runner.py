#!/usr/bin/env python3
"""
Session Runner — runs DE sessions via OpenClaw Gateway (chat completions).

Architecture: DE → OpenClaw Gateway → Eddie (has all tools: exec, browser, Telegram, etc.)
Eddie processes the task with his full capabilities and returns a structured work log.

Steps saved:
  trigger   — task description
  thinking  — (if model returns reasoning)
  result    — Eddie's completed work output
  complete  — final summary

For full per-step visibility (Reason/Act/Observe), a valid ANTHROPIC_API_KEY
pointing to a project with claude-sonnet-4-6 access is needed; then the
react_engine.py handles the loop directly. See README.md.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', 'http://127.0.0.1:18789')
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', '')
DE_MODEL = os.environ.get('DE_MODEL', 'claude-sonnet-4-6')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_step(session_file: Path, step_type: str, content: str):
    """Append a step to the session JSON and flush."""
    d = json.loads(session_file.read_text())
    d.setdefault('steps', []).append({
        'type': step_type,
        'content': content,
        'ts': _now(),
    })
    d['updated_at'] = _now()
    session_file.write_text(json.dumps(d, indent=2))


def call_openclaw(messages: list, session_key: str, timeout: int = 180) -> dict:
    """Single call to OpenClaw chat completions endpoint."""
    payload = json.dumps({
        'model': 'openclaw',
        'messages': messages,
        'user': session_key,   # stable key gives Eddie context across sessions
        'max_tokens': 4096,
    }).encode()
    req = Request(
        f'{OPENCLAW_GATEWAY_URL}/v1/chat/completions',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {OPENCLAW_GATEWAY_TOKEN}',
        },
        method='POST',
    )
    resp = urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def write_portal_inbox(de_name: str, title: str, body: str, level: int = 0):
    entry = {
        'ts': _now(), 'agent': de_name, 'level': level, 'type': 'session_done',
        'title': title, 'body': body,
    }
    inbox = AGENTS_DIR / 'portal-inbox.jsonl'
    with open(inbox, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def main():
    if len(sys.argv) < 3:
        print('Usage: session_runner.py <de_name> <session_id>')
        sys.exit(1)

    de_name = sys.argv[1]
    session_id = sys.argv[2]
    print(f'[session_runner] Starting: {de_name} / {session_id}')

    de_dir = AGENTS_DIR / de_name
    job_md_file = de_dir / 'job.md'
    de_json_file = de_dir / 'de.json'
    session_file = de_dir / 'sessions' / f'{session_id}.json'

    if not de_dir.exists() or not job_md_file.exists():
        print(f'ERROR: DE not found: {de_dir}')
        sys.exit(1)

    de_info = json.loads(de_json_file.read_text()) if de_json_file.exists() else {}
    job_md = job_md_file.read_text()
    session_raw = json.loads(session_file.read_text())

    trigger_type = session_raw.get('trigger_type', 'user')
    trigger_context = session_raw.get('trigger_context', 'Manual start')
    display_name = de_info.get('display_name', de_name.upper())
    role = de_info.get('role', 'Digital Employee')

    # Mark running + write trigger step
    session_raw['status'] = 'running'
    session_raw['started_at'] = _now()
    session_file.write_text(json.dumps(session_raw, indent=2))

    # Build task prompt
    task_prompt = (
        f'You are **{display_name}**, a Digital Employee with role: {role}.\n\n'
        f'== YOUR JOB ==\n{job_md[:5000]}\n\n'
        f'== CURRENT TASK ==\n'
        f'Trigger: {trigger_type}\n'
        f'Context: {trigger_context}\n\n'
        f'Execute your responsibilities now. Use your tools (exec, browser, Telegram, files, web search — whatever is available to you). '
        f'Structure your response as a clear work log:\n'
        f'1. What you did\n2. What tools/commands you ran\n3. Results/findings\n4. Next steps or scheduled follow-ups\n\n'
        f'Be specific and action-oriented. This log will be reviewed by your manager.'
    )

    # Write trigger step
    _write_step(session_file, 'trigger', trigger_context)

    print(f'[session_runner] Routing to Eddie via OpenClaw ({OPENCLAW_GATEWAY_URL})')

    try:
        response = call_openclaw(
            messages=[{'role': 'user', 'content': task_prompt}],
            session_key=f'de:{de_name}',
            timeout=180,
        )

        result_text = response['choices'][0]['message']['content'] or ''
        print(f'[session_runner] Got response ({len(result_text)} chars)')

        # Write result step
        _write_step(session_file, 'result', result_text)

        # Extract first ~200 chars as summary
        summary = result_text.strip()[:200].replace('\n', ' ')

        # Mark done
        d = json.loads(session_file.read_text())
        d['status'] = 'done'
        d['completed_at'] = _now()
        d['summary'] = summary
        session_file.write_text(json.dumps(d, indent=2))

        write_portal_inbox(de_name, title=f'✅ {display_name}: session done', body=summary)
        print(f'[session_runner] Done. Summary: {summary[:80]}')

    except Exception as e:
        tb = traceback.format_exc()
        print(f'[session_runner] ERROR: {e}\n{tb}')
        _write_step(session_file, 'error', f'{e}\n\n{tb[:500]}')
        d = json.loads(session_file.read_text())
        d['status'] = 'error'
        d['completed_at'] = _now()
        d['error'] = str(e)
        session_file.write_text(json.dumps(d, indent=2))
        write_portal_inbox(de_name, title=f'❌ {display_name}: error', body=str(e), level=2)
        sys.exit(1)


if __name__ == '__main__':
    main()
