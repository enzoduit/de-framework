#!/usr/bin/env python3
"""
Session Runner — runs DE sessions via either:

  A) Anthropic direct ReAct loop (when ANTHROPIC_API_KEY is set in environment)
     Uses react_engine.py + work_session.py for full multi-step Reason/Act/Observe visibility.

  B) OpenClaw Gateway single-call (fallback when no API key)
     Eddie processes the task with his full tool capabilities and returns a work log.

Engine is selected at runtime based on ANTHROPIC_API_KEY presence in env.
"""

import json
import os
import sys
import re
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
        'user': session_key,
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

    # Bootstrap: auto-create workspace dir + MEMORY.md if missing
    workspace_dir = de_dir / 'workspace'
    workspace_dir.mkdir(exist_ok=True)
    memory_file = workspace_dir / 'MEMORY.md'
    if not memory_file.exists():
        memory_file.write_text(
            f'# {de_info.get("display_name", de_name.upper())} — Memory\n\n'
            f'Initialized {_now()[:10]}. Write key decisions, findings, and progress here.\n'
        )
        print(f'[session_runner] Created MEMORY.md for {de_name}')
    session_raw = json.loads(session_file.read_text())

    trigger_type = session_raw.get('trigger_type', 'user')
    trigger_context = session_raw.get('trigger_context', 'Manual start')

    # ── Pre-fetch: run workspace/pre_fetch.py if exists (no LLM, injects live data) ──
    pre_fetch_script = workspace_dir / 'pre_fetch.py'
    if pre_fetch_script.exists():
        import subprocess as _sp
        try:
            result = _sp.run(
                ['python3', str(pre_fetch_script)],
                capture_output=True, text=True, timeout=30,
                env={**__import__('os').environ, 'AGENTS_DIR': str(AGENTS_DIR)}
            )
            if result.stdout.strip():
                trigger_context = result.stdout.strip() + '\n\n---\n\n' + trigger_context
                print(f'[session_runner] pre_fetch.py injected {len(result.stdout)} chars')
        except Exception as _e:
            print(f'[session_runner] pre_fetch.py failed (non-fatal): {_e}')
    display_name = de_info.get('display_name', de_name.upper())
    role = de_info.get('role', 'Digital Employee')

    # Mark running
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
        f'Execute your responsibilities now. Reason step by step through your mission. '
        f'For each action you decide to take, describe it clearly. '
        f'Structure your response as a clear work log:\n'
        f'1. What you assessed / observed\n'
        f'2. What actions you would take\n'
        f'3. Results/findings\n'
        f'4. Next steps or scheduled follow-ups\n\n'
        f'Be specific and action-oriented. This log will be reviewed by your manager.\n\n'
        f'== RL LOOP — DO THIS AFTER EVERY ACTION ==\n'
        f'After EACH meaningful action (publishing content, running a script, making a change, writing something), '
        f'call log_assumption IMMEDIATELY — right then, before your next step. Do not save it for the end. '
        f'If you are approaching the iteration limit with real, valuable work still left to do, call request_more_iterations first.'
    )

    # ─── RL Loop: inject due assumptions for measurement ──────────────────────
    try:
        from datetime import date as _date
        _af = de_dir / 'workspace' / 'assumptions.json'
        if _af.exists():
            import json as _json
            _today = _date.today().isoformat()
            _all = _json.loads(_af.read_text())
            _due = [a for a in _all if a.get('status') == 'pending' and a.get('check_date', '9999') <= _today]
            if _due:
                _section = '\n\n## ⚠️ PRIORITY — Measure These Pending Assumptions First\n\n'
                _section += 'Before your main task, measure each one below and call measure_assumption():\n\n'
                for _a in _due:
                    _section += f'**ID: {_a["id"]}**\n'
                    _section += f'- Action: {_a["action"]}\n'
                    _section += f'- Expected: {_a["expected_outcome"]}\n'
                    if _a.get('metric'):
                        _section += f'- How to measure: {_a["metric"]}\n'
                    _section += f'- Was due: {_a["check_date"]}\n'
                    _section += f'  → Call: measure_assumption(assumption_id=\"{_a["id"]}\", actual_result=\"...", reward=\"reward\"|\"disreward\", note=\"...")\n\n'
                task_prompt += _section
                print(f'[session_runner] {len(_due)} assumption(s) due for measurement injected')
    except Exception as _rl_err:
        print(f'[session_runner] RL check skipped: {_rl_err}')

    # Inject recent human feedback so the session learns from past corrections
    try:
        from feedback_db import get_recent_feedback
        recent_fb = get_recent_feedback(de_name, limit=5)
        if recent_fb:
            feedback_section = '\n\n## Recent Human Feedback (apply these learnings)\n'
            for f in recent_fb:
                feedback_section += f"- [{f['timestamp'][:10]}] {f['raw_text']}\n"
            task_prompt += feedback_section
    except Exception as _fb_err:
        print(f'[session_runner] feedback injection skipped: {_fb_err}')

    # ── Engine Selection ────────────────────────────────────────────────────────
    # ANTHROPIC_API_KEY is injected via /etc/de-framework.env (EnvironmentFile in service)
    ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

    if ANTHROPIC_KEY:
        # ── Path A: Anthropic direct ReAct loop ────────────────────────────────
        from react_engine import ReActEngine
        from work_session import WorkSession
        print('[session_runner] Engine: Anthropic direct ReAct')

        # Load the existing session file as a WorkSession — this lets the engine
        # write steps (reasoning/action/observation) directly to the same JSON
        # that the portal reads for live step display.
        ws = WorkSession.load(de_name, session_id)

        # DE-specific tool definitions from de.json (may be empty list)
        # de.json stores tool IDs as strings — convert to full dicts with implementations
        from tool_implementations import get_tool_defs
        de_tools = get_tool_defs(de_info.get('tools', []))

        engine = ReActEngine(
            agent_name=de_name,
            mission=task_prompt,
            tools=de_tools,
            max_iterations=15,
            model='claude-sonnet-4-6',
            session=ws,
        )

        try:
            result = engine.run()
            summary = result.get('summary', '') or ''

            # Ensure completed_at is stamped (WorkSession.set_status sets status
            # but not completed_at on the outer JSON — sync it here)
            d = json.loads(session_file.read_text())
            if 'completed_at' not in d:
                d['completed_at'] = _now()
            session_file.write_text(json.dumps(d, indent=2))

            iterations = result.get('iterations', 0)
            body = summary[:200] if summary else f'ReAct loop complete in {iterations} iterations (status: {result.get("status")})'
            write_portal_inbox(de_name, title=f'✅ {display_name}: session done', body=body)
            print(f'[session_runner] ReAct done. Status: {result.get("status")} ({iterations} iterations)')

        except Exception as e:
            tb = traceback.format_exc()
            print(f'[session_runner] ReAct ERROR: {e}\n{tb}')
            _write_step(session_file, 'error', f'{e}\n\n{tb[:500]}')
            d = json.loads(session_file.read_text())
            d['status'] = 'error'
            d['completed_at'] = _now()
            d['error'] = str(e)
            session_file.write_text(json.dumps(d, indent=2))
            write_portal_inbox(de_name, title=f'❌ {display_name}: error', body=str(e), level=2)
            sys.exit(1)

    else:
        # ── Path B: Single-call via OpenClaw Gateway (fallback) ────────────────
        _write_step(session_file, 'trigger', trigger_context)
        print(f'[session_runner] Engine: OpenClaw single-call ({OPENCLAW_GATEWAY_URL})')

        try:
            response = call_openclaw(
                messages=[{'role': 'user', 'content': task_prompt}],
                session_key=f'de:{de_name}',
                timeout=180,
            )

            result_text = response['choices'][0]['message']['content'] or ''
            print(f'[session_runner] Got response ({len(result_text)} chars)')

            _write_step(session_file, 'result', result_text)

            # Strip markdown for clean summary
            _s = re.sub(r'#{1,6}\s+', '', result_text)
            _s = re.sub(r'\*\*|__|_|\*|`{1,3}', '', _s)
            _s = re.sub(r'\|', ' ', _s)
            _s = re.sub(r'---+', '', _s)
            _s = re.sub(r'\s+', ' ', _s).strip()
            summary = _s[:200]

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
