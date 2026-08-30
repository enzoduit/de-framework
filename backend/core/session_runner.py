#!/usr/bin/env python3
"""
Session Runner — executes a queued WorkSession for a Digital Employee.
Usage: python3 session_runner.py <de_name> <session_id>

Picks up a queued session, sets it to running, runs the ReAct loop
with standard tools, logs every step to the session file.
"""

import json
import os
import sys
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# Path from environment variable — no hardcoded assumptions
AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', './agents'))

def _now():
    return datetime.now(timezone.utc).isoformat()

# ── Standard tools available to all DEs ────────────────────────────────────

def tool_read_file(inp):
    path = inp.get('path', '')
    try:
        p = Path(path)
        if not p.exists():
            return f'File not found: {path}'
        content = p.read_text()
        if len(content) > 4000:
            return content[:4000] + f'\n... [truncated, {len(content)} total chars]'
        return content
    except Exception as e:
        return f'Error reading {path}: {e}'

def tool_write_file(inp):
    path = inp.get('path', '')
    content = inp.get('content', '')
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f'Written {len(content)} chars to {path}'
    except Exception as e:
        return f'Error writing {path}: {e}'

def tool_list_dir(inp):
    path = inp.get('path', '')
    try:
        p = Path(path)
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [f"{'[DIR]' if e.is_dir() else '[FILE]'} {e.name}" for e in entries[:50]]
        return '\n'.join(lines) or '(empty)'
    except Exception as e:
        return f'Error listing {path}: {e}'

def tool_exec(inp):
    cmd = inp.get('command', '')
    if not cmd:
        return 'No command provided'
    # Safety: block destructive commands
    blocked = ['rm -rf', 'shutdown', 'reboot', 'dd if=', 'mkfs']
    for b in blocked:
        if b in cmd:
            return f'Blocked: command contains "{b}"'
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
            cwd=str(AGENTS_DIR)
        )
        out = (result.stdout + result.stderr).strip()
        return out[:3000] if out else '(no output)'
    except subprocess.TimeoutExpired:
        return 'Command timed out after 30s'
    except Exception as e:
        return f'Error: {e}'

def tool_http_get(inp):
    url = inp.get('url', '')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Eddie-DE/1.0'})
        r = urllib.request.urlopen(req, timeout=10)
        data = r.read().decode('utf-8', errors='replace')
        return data[:3000] if len(data) > 3000 else data
    except Exception as e:
        return f'Error fetching {url}: {e}'

def tool_read_json(inp):
    path = inp.get('path', '')
    key = inp.get('key', None)
    try:
        data = json.loads(Path(path).read_text())
        if key:
            return json.dumps(data.get(key, f'Key "{key}" not found'), indent=2)
        return json.dumps(data, indent=2)[:3000]
    except Exception as e:
        return f'Error: {e}'

def make_tool_schedule_activity(de_name):
    """Factory: returns the schedule_next_activity tool fn bound to de_name."""
    def _impl(inp):
        import uuid as _uid
        from datetime import datetime, timedelta, timezone
        title = inp.get('title', 'Scheduled activity')
        trigger_context = inp.get('trigger_context', '')
        frequency = inp.get('frequency', 'once')
        time_utc = inp.get('time_utc', '08:00')
        next_run_in = inp.get('next_run_in', '')
        now = datetime.now(timezone.utc)
        if next_run_in:
            unit = next_run_in[-1] if next_run_in else 'h'
            try:
                val = int(next_run_in[:-1])
            except ValueError:
                val = 24
            delta = timedelta(hours=val) if unit == 'h' else (
                timedelta(days=val) if unit == 'd' else timedelta(weeks=val))
            next_run_at = (now + delta).isoformat()
        else:
            h, m = 8, 0
            if ':' in time_utc:
                try: h, m = map(int, time_utc.split(':'))
                except: pass
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            next_run_at = candidate.isoformat()
        activity = {
            'id': _uid.uuid4().hex[:8],
            'title': title, 'frequency': frequency, 'time_utc': time_utc,
            'trigger_context': trigger_context, 'created_by': 'agent',
            'last_run_at': None, 'next_run_at': next_run_at, 'run_count': 0,
        }
        schedule_file = AGENTS_DIR / de_name / 'schedule.json'
        try:
            schedule = json.loads(schedule_file.read_text()) if schedule_file.exists() else {'activities': []}
        except Exception:
            schedule = {'activities': []}
        schedule.setdefault('activities', []).append(activity)
        schedule['updated_at'] = _now()
        schedule_file.write_text(json.dumps(schedule, indent=2))
        # Portal notification
        entry = {'ts': _now(), 'agent': de_name, 'level': 0, 'type': 'scheduled',
                 'title': f'\U0001f4c5 Scheduled: {title}',
                 'body': f'Next: {next_run_at} | {frequency} | {trigger_context[:150]}'}
        inbox = AGENTS_DIR / 'portal-inbox.jsonl'
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(inbox, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return {'status': 'scheduled', 'activity_id': activity['id'],
                'next_run_at': next_run_at, 'title': title}
    return _impl


def tool_update_metrics(inp):
    """Update the DE's metrics.json with provided key-value pairs."""
    de_name = inp.get('de_name', '')
    updates = inp.get('updates', {})
    if not de_name or not updates:
        return 'Missing de_name or updates'
    metrics_file = AGENTS_DIR / de_name / 'metrics.json'
    try:
        metrics = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
        metrics.update(updates)
        metrics['last_updated'] = _now()
        metrics_file.write_text(json.dumps(metrics, indent=2))
        return f'Updated metrics.json with {list(updates.keys())}'
    except Exception as e:
        return f'Error: {e}'

def tool_write_portal_inbox(inp):
    """Write an update to portal-inbox.jsonl."""
    de_name = inp.get('de_name', '')
    message = inp.get('message', '')
    level = inp.get('level', 0)
    if not de_name or not message:
        return 'Missing de_name or message'
    entry = {
        'ts': _now(),
        'agent': de_name,
        'level': level,
        'type': 'session_update',
        'title': message[:100],
        'body': message,
        'status': 'info',
    }
    inbox = AGENTS_DIR / 'portal-inbox.jsonl'
    with open(inbox, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    return f'Written to portal-inbox: {message[:80]}'

# ── Build tools list for ReActEngine ───────────────────────────────────────

def _get_schedule_context(de_name, de_dir):
    """Return schedule context string to inject into the session mission."""
    schedule_file = de_dir / 'schedule.json'
    if not schedule_file.exists():
        return ''
    try:
        schedule_data = json.loads(schedule_file.read_text())
        activities = schedule_data.get('activities', [])
        now_dt = datetime.now(timezone.utc)
        due, upcoming = [], []
        for a in activities:
            nr = a.get('next_run_at', '')
            if not nr:
                continue
            try:
                nr_dt = datetime.fromisoformat(nr.replace('Z', '+00:00'))
                if nr_dt <= now_dt:
                    due.append(a)
                else:
                    upcoming.append(a)
            except Exception:
                pass
        parts = []
        if due:
            parts.append('## SCHEDULED ACTIVITIES DUE THIS SESSION')
            for a in due:
                parts.append(f'\n### {a["title"]} ({a.get("frequency", "once")})')
                if a.get('trigger_context'):
                    parts.append(a['trigger_context'])
        if upcoming and not due:
            upcoming_sorted = sorted(upcoming, key=lambda x: x.get('next_run_at', ''))[:3]
            parts.append('## UPCOMING SCHEDULED ACTIVITIES')
            for a in upcoming_sorted:
                parts.append(f'- {a["title"]}: next at {a.get("next_run_at", "?")} ({a.get("frequency", "once")})')
        return '\n'.join(parts)
    except Exception:
        return ''


def build_tools(de_name):
    return [
        {
            'name': 'read_file',
            'description': 'Read a file from the filesystem. Use for reading job.md, metrics.json, memory.md, log files, etc.',
            'input_schema': {'type': 'object', 'required': ['path'], 'properties': {
                'path': {'type': 'string', 'description': 'Absolute or relative file path'}
            }},
            'fn': tool_read_file,
        },
        {
            'name': 'write_file',
            'description': 'Write content to a file. Use to update metrics.json, memory.md, or workspace files.',
            'input_schema': {'type': 'object', 'required': ['path', 'content'], 'properties': {
                'path': {'type': 'string'},
                'content': {'type': 'string'},
            }},
            'fn': tool_write_file,
        },
        {
            'name': 'list_directory',
            'description': 'List files in a directory.',
            'input_schema': {'type': 'object', 'required': ['path'], 'properties': {
                'path': {'type': 'string'},
            }},
            'fn': tool_list_dir,
        },
        {
            'name': 'exec_command',
            'description': 'Run a shell command. Use for checking services, running scripts, reading system state. Avoid destructive commands.',
            'input_schema': {'type': 'object', 'required': ['command'], 'properties': {
                'command': {'type': 'string', 'description': 'Shell command to run'},
            }},
            'fn': tool_exec,
        },
        {
            'name': 'http_get',
            'description': 'Make an HTTP GET request to a URL. Use for checking API endpoints, service health, etc.',
            'input_schema': {'type': 'object', 'required': ['url'], 'properties': {
                'url': {'type': 'string'},
            }},
            'fn': tool_http_get,
        },
        {
            'name': 'read_json',
            'description': 'Read and parse a JSON file, optionally extracting a specific key.',
            'input_schema': {'type': 'object', 'required': ['path'], 'properties': {
                'path': {'type': 'string'},
                'key': {'type': 'string', 'description': 'Optional: specific key to extract'},
            }},
            'fn': tool_read_json,
        },
        {
            'name': 'update_metrics',
            'description': f'Update {de_name}\'s metrics.json with new values.',
            'input_schema': {'type': 'object', 'required': ['updates'], 'properties': {
                'de_name': {'type': 'string', 'default': de_name},
                'updates': {'type': 'object', 'description': 'Key-value pairs to update in metrics.json'},
            }},
            'fn': tool_update_metrics,
        },
        {
            'name': 'schedule_next_activity',
            'description': (
                'Plan the next work session for this DE. Call when you find something needing '
                'follow-up, or to establish a recurring check. The trigger_context is injected '
                'as specific questions into that future session.'
            ),
            'input_schema': {'type': 'object', 'required': ['title', 'trigger_context'], 'properties': {
                'title': {'type': 'string', 'description': 'Short activity name, e.g. "Follow up on incident #5"'},
                'trigger_context': {'type': 'string', 'description': 'The questions and focus for the next session. Be specific: what to check, what to look for, what to fix.'},
                'frequency': {'type': 'string', 'enum': ['once', 'daily', 'weekly', 'monthly'],
                              'description': 'Recurrence. Use "once" for one-time follow-ups (default).'},
                'next_run_in': {'type': 'string', 'description': 'Relative time: "2h", "1d", "1w". For one-time follow-ups.'},
                'time_utc': {'type': 'string', 'description': 'UTC time for recurring runs, e.g. "08:00"'},
            }},
            'fn': make_tool_schedule_activity(de_name),
        },
        {
            'name': 'write_portal_inbox',
            'description': 'Write an update or finding to the portal inbox so Ed can see it.',
            'input_schema': {'type': 'object', 'required': ['message'], 'properties': {
                'de_name': {'type': 'string', 'default': de_name},
                'message': {'type': 'string', 'description': 'Message to write (max 500 chars)'},
                'level': {'type': 'integer', 'description': '0=info, 1=action taken, 2=needs approval'},
            }},
            'fn': tool_write_portal_inbox,
        },
    ]

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print('Usage: session_runner.py <de_name> <session_id> [--resume <json>]')
        sys.exit(1)

    de_name = sys.argv[1]
    session_id = sys.argv[2]

    # Parse optional --resume flag
    resume_data = None
    if '--resume' in sys.argv:
        idx = sys.argv.index('--resume')
        if idx + 1 < len(sys.argv):
            try:
                resume_data = json.loads(sys.argv[idx + 1])
            except Exception:
                pass

    print(f'[session_runner] Starting: {de_name} / {session_id}' + (' [RESUME]' if resume_data else ''))

    # Load WorkSession
    try:
        from work_session import WorkSession
    except ImportError:
        print('ERROR: work_session.py not found')
        sys.exit(1)

    # Check DE exists
    de_dir = AGENTS_DIR / de_name
    job_md_file = de_dir / 'job.md'
    de_json_file = de_dir / 'de.json'

    if not de_dir.exists() or not job_md_file.exists():
        print(f'ERROR: DE not found: {de_name}')
        sys.exit(1)

    # Read existing session file first to get trigger params
    session_file = de_dir / 'sessions' / f'{session_id}.json'
    if not session_file.exists():
        print(f'ERROR: Session file not found: {session_file}')
        sys.exit(1)
    session_raw = json.loads(session_file.read_text())
    trigger_type = session_raw.get('trigger_type', 'user')
    trigger_from = session_raw.get('trigger_from')
    trigger_context_val = session_raw.get('trigger_context', 'Manual start')

    # Load existing session (pass params so WorkSession signature is satisfied)
    session = WorkSession(
        de_name=de_name,
        trigger_type=trigger_type,
        trigger_from=trigger_from,
        trigger_context=trigger_context_val,
        session_id=session_id,
    )
    session.set_status('running')

    session_data = session.data
    trigger_context = session_data.get('trigger_context', 'Manual session start')
    trigger_type = session_data.get('trigger_type', 'user')

    print(f'[session_runner] Session loaded, trigger: {trigger_type} — {trigger_context}')

    # Load mission
    job_md = job_md_file.read_text()
    de_info = {}
    if de_json_file.exists():
        de_info = json.loads(de_json_file.read_text())

    display_name = de_info.get('display_name', de_name.upper())
    role = de_info.get('role', '')

    # Load scheduled activities due this session
    schedule_context = _get_schedule_context(de_name, de_dir)

    mission = f"""You are {display_name}, {role}.

Your full job description and responsibilities:
---
{job_md[:6000]}
---
{schedule_context}

CURRENT WORK SESSION:
Trigger type: {trigger_type}
Trigger context: {trigger_context}
Session ID: {session_id}
Started: {_now()}

Your workspace: {de_dir}
Your files: metrics.json, memory.md, decisions.json (all in your directory)

INSTRUCTIONS:
1. Review your current metrics and recent activity
2. Perform your regular duties appropriate to this trigger
3. Document findings using write_portal_inbox for important items
4. Update metrics.json with current KPIs using update_metrics
5. If you need human approval, use request_human_decision (this pauses the session)
6. If you need a colleague's input, use ask_colleague
7. End with a clear summary of what you did

Be specific and action-oriented. Don't just read files — analyze and act.
Maximum 8 iterations. Work efficiently.
"""

    # If resuming after a human decision: inject the decision result into the mission
    if resume_data:
        approved = resume_data.get('approved', False)
        dec_note = resume_data.get('note', '') or 'No additional note.'
        dec_context = f"""

## ✅ RESUMED AFTER HUMAN DECISION
Your previous `request_human_decision` call was reviewed by Ed.
Decision: {'APPROVED ✅' if approved else 'REJECTED ❌'}
Ed's note: {dec_note}
Decision ID: {resume_data.get('decision_id', '')}

This session was paused and is now resuming. Continue your work based on this decision.
Review your session history to understand what you were doing before pausing.
"""
        mission += dec_context
        session.set_status('running')
        session.add_step('decision_response', approved=approved, note=dec_note)
        print(f'[session_runner] Resuming after decision: {"APPROVED" if approved else "REJECTED"}')

    # Import and run ReActEngine
    sys.path.insert(0, str(AGENTS_DIR))
    try:
        from react_engine import ReActEngine
    except ImportError as e:
        print(f'ERROR importing react_engine: {e}')
        session.set_status('error', summary=f'Import error: {e}')
        sys.exit(1)

    tools = build_tools(de_name)

    # Max iterations: per-agent override in de.json (max_iterations), else DE_MAX_ITERATIONS env, else 8
    default_max_iter = int(os.environ.get('DE_MAX_ITERATIONS', 8))
    max_iter = de_info.get('max_iterations', default_max_iter)

    engine = ReActEngine(
        agent_name=de_name,
        mission=mission,
        tools=tools,
        max_iterations=max_iter,
        model=de_info.get('model') or os.environ.get('DE_MODEL', 'claude-haiku-4-5'),
        session=session,
    )

    print(f'[session_runner] Running ReAct loop...')
    try:
        result = engine.run()
        print(f'[session_runner] Complete: {result["status"]} ({result["iterations"]} iterations)')
    except Exception as e:
        print(f'[session_runner] ERROR: {e}')
        session.set_status('error', summary=str(e))

if __name__ == '__main__':
    main()
