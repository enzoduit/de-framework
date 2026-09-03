#!/usr/bin/env python3
"""
Session Runner — routes DE tasks to OpenClaw Gateway (Eddie).
All AI execution happens via POST /v1/chat/completions → OpenClaw → Eddie.
Eddie runs with ALL his tools (Telegram, browser, exec, files, skills, etc.)

Usage: python3 session_runner.py <de_name> <session_id>
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', './agents'))
OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', 'http://127.0.0.1:18789')
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', '')


def _now():
    return datetime.now(timezone.utc).isoformat()


def route_to_openclaw(de_name: str, session_id: str, task_prompt: str) -> str:
    """Send task to Eddie via OpenClaw chatCompletions endpoint.

    Uses stable user= session key so Eddie remembers context between runs
    of the same DE (de:<name>:<session_id> gives per-session isolation;
    use de:<name> for persistent cross-session memory — choose per use-case).
    """
    from openai import OpenAI

    client = OpenAI(
        base_url=f"{OPENCLAW_GATEWAY_URL}/v1",
        api_key=OPENCLAW_GATEWAY_TOKEN,
    )

    response = client.chat.completions.create(
        model="openclaw/default",
        messages=[{"role": "user", "content": task_prompt}],
        # Stable session key = Eddie remembers this DE's context across runs
        user=f"de:{de_name}",
        timeout=120,
    )

    return response.choices[0].message.content


def build_onboarding_prompt(de_name: str, display_name: str, role: str, job_md: str) -> str:
    return f"""Du wirst jetzt als Digital Employee "{display_name}" ({role}) im DE Framework eingesetzt.

Dies ist deine erste Session (Onboarding). Bitte:
1. Bestätige welche Tools dir zur Verfügung stehen (exec, browser, message/Telegram, files, etc.)
2. Lies die folgende Job-Beschreibung durch und bestätige dass du sie verstanden hast
3. Gib einen kurzen strukturierten Überblick: Tools verfügbar, bereit für Missions

Job-Beschreibung (job.md):
---
{job_md[:4000]}
---

Antworte strukturiert auf Deutsch."""


def build_task_prompt(
    de_name: str,
    display_name: str,
    role: str,
    job_md: str,
    trigger_type: str,
    trigger_context: str,
    session_id: str,
) -> str:
    return f"""Du arbeitest jetzt als Digital Employee "{display_name}" ({role}).

Deine Mission (job.md):
---
{job_md[:5000]}
---

Aktueller Work-Session Task:
- Trigger-Typ: {trigger_type}
- Context: {trigger_context}
- Session-ID: {session_id}

Führe deine Aufgaben durch. Du hast Zugriff auf alle deine Tools (Telegram, Browser, Files, exec, etc.).
Berichte am Ende strukturiert was du getan hast und was das Ergebnis ist."""


def update_session(session_file: Path, session_raw: dict, **updates):
    session_raw.update(updates)
    session_file.write_text(json.dumps(session_raw, indent=2))


def write_portal_inbox(de_name: str, title: str, body: str, level: int = 0):
    entry = {
        'ts': _now(), 'agent': de_name, 'level': level, 'type': 'session_done',
        'title': title, 'body': body,
    }
    inbox = AGENTS_DIR / 'portal-inbox.jsonl'
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
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

    # Validate
    if not de_dir.exists() or not job_md_file.exists():
        print(f'ERROR: DE not found at {de_dir}')
        sys.exit(1)
    if not session_file.exists():
        print(f'ERROR: Session file not found: {session_file}')
        sys.exit(1)

    # Load configs
    de_info = json.loads(de_json_file.read_text()) if de_json_file.exists() else {}
    job_md = job_md_file.read_text()
    session_raw = json.loads(session_file.read_text())

    trigger_type = session_raw.get('trigger_type', 'user')
    trigger_context = session_raw.get('trigger_context', 'Manual start')
    display_name = de_info.get('display_name', de_name.upper())
    role = de_info.get('role', 'Digital Employee')

    # Mark session as running
    update_session(session_file, session_raw, status='running', started_at=_now())

    # Detect onboarding (first run)
    capabilities_file = de_dir / 'capabilities.json'
    is_onboarding = not capabilities_file.exists()

    if is_onboarding:
        print(f'[session_runner] Onboarding session — querying capabilities from Eddie')
        task_prompt = build_onboarding_prompt(de_name, display_name, role, job_md)
    else:
        task_prompt = build_task_prompt(
            de_name, display_name, role, job_md,
            trigger_type, trigger_context, session_id,
        )

    print(f'[session_runner] Routing to Eddie via {OPENCLAW_GATEWAY_URL}')

    try:
        result = route_to_openclaw(de_name, session_id, task_prompt)

        # Log result to session
        steps = session_raw.get('steps', [])
        steps.append({
            'ts': _now(),
            'type': 'openclaw_response',
            'content': result,
        })
        update_session(session_file, session_raw,
                       status='done', completed_at=_now(), result=result, steps=steps)

        # Save capabilities on first run
        if is_onboarding:
            capabilities_file.write_text(json.dumps({
                'onboarding_ts': _now(),
                'response': result,
                'de_name': de_name,
            }, indent=2))
            print(f'[session_runner] ✅ Onboarding done — capabilities.json saved')

        # Portal inbox notification
        write_portal_inbox(
            de_name,
            title=f'✅ {display_name}: session complete',
            body=result[:500],
        )

        print(f'[session_runner] Done. Result snippet: {result[:120]}...')

    except Exception as e:
        print(f'[session_runner] ERROR: {e}')
        update_session(session_file, session_raw, status='error', error=str(e), completed_at=_now())
        write_portal_inbox(de_name, title=f'❌ {display_name}: session error', body=str(e), level=2)
        sys.exit(1)


if __name__ == '__main__':
    main()
