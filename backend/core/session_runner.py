#!/usr/bin/env python3
"""
Session Runner — runs DE sessions using the local ReAct engine.
Each session: reads job.md → builds tools → runs ReAct loop → saves steps.

Usage: python3 session_runner.py <de_name> <session_id>
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
WORKSPACE_DIR = Path('/root/.openclaw/workspace')

# Add backend/ to path so we can import react_engine / work_session
_BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND_DIR.parent))  # de-framework root
sys.path.insert(0, str(Path(__file__).parent))  # core/


def _now():
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def tool_exec_shell(inp: dict) -> str:
    """Run a shell command and return stdout/stderr (max 2000 chars)."""
    cmd = inp.get('command', '').strip()
    if not cmd:
        return json.dumps({'error': 'command is required'})
    timeout = int(inp.get('timeout_seconds', 30))
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
        if len(output) > 2000:
            output = output[:1900] + '\n...[truncated]'
        return json.dumps({
            'returncode': result.returncode,
            'output': output,
            'ok': result.returncode == 0,
        })
    except subprocess.TimeoutExpired:
        return json.dumps({'error': f'Command timed out after {timeout}s'})
    except Exception as e:
        return json.dumps({'error': str(e)})


def make_tool_read_file(de_name: str):
    def tool_read_file(inp: dict) -> str:
        """Read a file from workspace or DE workspace."""
        path_str = inp.get('path', '').strip()
        if not path_str:
            return json.dumps({'error': 'path is required'})
        # Resolve path — allow workspace/ or de workspace
        p = Path(path_str)
        if not p.is_absolute():
            # Try DE workspace first
            de_ws = AGENTS_DIR / de_name / 'workspace' / path_str
            if de_ws.exists():
                p = de_ws
            else:
                p = WORKSPACE_DIR / path_str
        # Safety: must be under workspace or de-agents
        p = p.resolve()
        allowed = [WORKSPACE_DIR.resolve(), AGENTS_DIR.resolve()]
        if not any(str(p).startswith(str(a)) for a in allowed):
            return json.dumps({'error': f'Access denied: path outside allowed dirs'})
        if not p.exists():
            return json.dumps({'error': f'File not found: {p}'})
        try:
            content = p.read_text(errors='replace')
            if len(content) > 3000:
                content = content[:2900] + '\n...[truncated]'
            return json.dumps({'path': str(p), 'content': content})
        except Exception as e:
            return json.dumps({'error': str(e)})
    return tool_read_file


def make_tool_write_file(de_name: str):
    def tool_write_file(inp: dict) -> str:
        """Write content to a file in the DE's workspace."""
        path_str = inp.get('path', '').strip()
        content = inp.get('content', '')
        if not path_str:
            return json.dumps({'error': 'path is required'})
        de_ws = AGENTS_DIR / de_name / 'workspace'
        de_ws.mkdir(parents=True, exist_ok=True)
        # If absolute path given, check it's safe
        p = Path(path_str)
        if p.is_absolute():
            p = p.resolve()
            if not str(p).startswith(str(de_ws.resolve())):
                return json.dumps({'error': 'write_file: can only write to DE workspace'})
        else:
            p = de_ws / path_str
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(content)
            return json.dumps({'ok': True, 'path': str(p), 'bytes': len(content)})
        except Exception as e:
            return json.dumps({'error': str(e)})
    return tool_write_file


def tool_send_telegram(inp: dict) -> str:
    """Send a Telegram message to Ed's thread."""
    text = inp.get('text', '').strip()
    if not text:
        return json.dumps({'error': 'text is required'})
    # Override chat/topic if provided
    chat_id = inp.get('chat_id', -1003728024208)
    topic_id = inp.get('topic_id', 7694)
    try:
        oc_cfg = json.loads(Path('/root/.openclaw/openclaw.json').read_text())
        bot_token = oc_cfg['telegram']['accounts'][0]['botToken']
    except Exception as e:
        return json.dumps({'error': f'Could not load bot token: {e}'})
    import urllib.request
    payload = json.dumps({
        'chat_id': chat_id,
        'message_thread_id': topic_id,
        'text': text,
        'parse_mode': 'HTML',
    }).encode()
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            data=payload, headers={'Content-Type': 'application/json'}, method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return json.dumps({'ok': data.get('ok', False), 'message_id': data.get('result', {}).get('message_id')})
    except Exception as e:
        return json.dumps({'error': str(e)})


def tool_web_search(inp: dict) -> str:
    """Search the web via Perplexity API and return results."""
    query = inp.get('query', '').strip()
    if not query:
        return json.dumps({'error': 'query is required'})
    # Load PPLX key
    pplx_key = ''
    try:
        bench = Path('/root/.openclaw/workspace/skills/geo-optimizer/run_benchmark.py')
        if bench.exists():
            for line in bench.read_text().split('\n'):
                if 'PERPLEXITY_API_KEY' in line and '=' in line:
                    pplx_key = line.split('=', 1)[1].strip().strip('"\'')
                    break
    except Exception:
        pass
    if not pplx_key:
        return json.dumps({'error': 'PPLX API key not found'})
    import urllib.request
    payload = json.dumps({
        'model': 'sonar',
        'messages': [{'role': 'user', 'content': query}],
        'max_tokens': 800,
    }).encode()
    try:
        req = urllib.request.Request(
            'https://api.perplexity.ai/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {pplx_key}'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=20)
        data = json.loads(resp.read())
        content = data['choices'][0]['message']['content']
        citations = data.get('citations', [])[:5]
        return json.dumps({'answer': content[:1500], 'citations': citations})
    except Exception as e:
        return json.dumps({'error': str(e)})


def make_tool_schedule_next_session(de_name: str):
    def tool_schedule_next_session(inp: dict) -> str:
        """Schedule a follow-up session for this DE."""
        title = inp.get('title', 'Scheduled follow-up')
        when_iso = inp.get('when_iso', '')  # ISO datetime or empty for +1 day
        trigger_context = inp.get('trigger_context', title)
        frequency = inp.get('frequency', 'once')
        if not when_iso:
            from datetime import timedelta
            when_iso = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
                hour=8, minute=0, second=0, microsecond=0
            ).isoformat()
        schedule_file = AGENTS_DIR / de_name / 'schedule.json'
        try:
            schedule = json.loads(schedule_file.read_text()) if schedule_file.exists() else {'activities': []}
        except Exception:
            schedule = {'activities': []}
        import uuid
        activity = {
            'id': uuid.uuid4().hex[:8],
            'title': title,
            'frequency': frequency,
            'trigger_context': trigger_context,
            'created_by': 'de_self',
            'next_run_at': when_iso,
            'last_run_at': None,
            'run_count': 0,
        }
        schedule.setdefault('activities', []).append(activity)
        schedule['updated_at'] = _now()
        schedule_file.write_text(json.dumps(schedule, indent=2))
        return json.dumps({'ok': True, 'activity_id': activity['id'], 'next_run_at': when_iso})
    return tool_schedule_next_session


def make_tool_list_workspace_files(de_name: str):
    def tool_list_workspace_files(inp: dict) -> str:
        """List files in the DE workspace directory."""
        subpath = inp.get('path', '').strip('/')
        de_ws = AGENTS_DIR / de_name / 'workspace'
        if subpath:
            target = de_ws / subpath
        else:
            target = de_ws
        target = target.resolve()
        # Safety
        if not str(target).startswith(str(de_ws.resolve())):
            return json.dumps({'error': 'Access denied'})
        try:
            result = subprocess.run(
                ['ls', '-la', str(target)], capture_output=True, text=True, timeout=5
            )
            return json.dumps({'listing': result.stdout or result.stderr})
        except Exception as e:
            return json.dumps({'error': str(e)})
    return tool_list_workspace_files


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions for Anthropic API
# ─────────────────────────────────────────────────────────────────────────────

def build_tools(de_name: str) -> list:
    return [
        {
            'name': 'exec_shell',
            'description': (
                'Execute a shell command on the server. Returns stdout+stderr. '
                'Use for system checks, file ops, running scripts. Max 2000 chars output.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string', 'description': 'Shell command to execute'},
                    'timeout_seconds': {'type': 'integer', 'description': 'Timeout in seconds (default 30)', 'default': 30},
                },
                'required': ['command'],
            },
            'fn': tool_exec_shell,
        },
        {
            'name': 'read_file',
            'description': (
                'Read a file. For relative paths, looks in DE workspace first, then global workspace. '
                'Returns file content (max 3000 chars).'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'File path (absolute or relative to workspace)'},
                },
                'required': ['path'],
            },
            'fn': make_tool_read_file(de_name),
        },
        {
            'name': 'write_file',
            'description': (
                'Write content to a file in the DE\'s workspace (/var/de-agents/<name>/workspace/). '
                'Creates parent directories automatically.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'File path (relative to DE workspace)'},
                    'content': {'type': 'string', 'description': 'File content to write'},
                },
                'required': ['path', 'content'],
            },
            'fn': make_tool_write_file(de_name),
        },
        {
            'name': 'send_telegram',
            'description': (
                'Send a Telegram message to Ed\'s main notification thread. '
                'Use for important alerts, status updates, or results.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Message text (HTML formatting supported)'},
                    'chat_id': {'type': 'integer', 'description': 'Chat ID (default: -1003728024208)', 'default': -1003728024208},
                    'topic_id': {'type': 'integer', 'description': 'Topic/thread ID (default: 7694)', 'default': 7694},
                },
                'required': ['text'],
            },
            'fn': tool_send_telegram,
        },
        {
            'name': 'web_search',
            'description': (
                'Search the web using Perplexity AI. Returns an answer with citations. '
                'Use for checking current info, AI search visibility, competitor research.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Search query'},
                },
                'required': ['query'],
            },
            'fn': tool_web_search,
        },
        {
            'name': 'schedule_next_session',
            'description': (
                'Schedule a follow-up session for this DE. Use for self-scheduling future work.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': 'Title for the scheduled session'},
                    'trigger_context': {'type': 'string', 'description': 'Context to pass to the future session'},
                    'when_iso': {'type': 'string', 'description': 'ISO datetime for when to run (default: tomorrow 08:00 UTC)'},
                    'frequency': {'type': 'string', 'description': 'once|daily|weekly (default: once)', 'default': 'once'},
                },
                'required': ['title'],
            },
            'fn': make_tool_schedule_next_session(de_name),
        },
        {
            'name': 'list_workspace_files',
            'description': 'List files in the DE\'s workspace directory.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'Subdirectory within DE workspace (optional)'},
                },
                'required': [],
            },
            'fn': make_tool_list_workspace_files(de_name),
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

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

    print(f'[session_runner] Starting ReAct: {de_name} / {session_id}')

    de_dir = AGENTS_DIR / de_name
    job_md_file = de_dir / 'job.md'
    de_json_file = de_dir / 'de.json'
    session_file = de_dir / 'sessions' / f'{session_id}.json'

    if not de_dir.exists() or not job_md_file.exists():
        print(f'ERROR: DE not found at {de_dir}')
        sys.exit(1)
    if not session_file.exists():
        print(f'ERROR: Session file not found: {session_file}')
        sys.exit(1)

    de_info = json.loads(de_json_file.read_text()) if de_json_file.exists() else {}
    job_md = job_md_file.read_text()
    session_raw = json.loads(session_file.read_text())

    trigger_type = session_raw.get('trigger_type', 'user')
    trigger_context = session_raw.get('trigger_context', 'Manual start')
    display_name = de_info.get('display_name', de_name.upper())
    role = de_info.get('role', 'Digital Employee')

    # Mark as running
    session_raw['status'] = 'running'
    session_raw['started_at'] = _now()
    session_file.write_text(json.dumps(session_raw, indent=2))

    # Build mission for ReAct engine
    mission = (
        f'You are {display_name}, a Digital Employee with role: {role}.\n\n'
        f'Your job description:\n{job_md[:6000]}\n\n'
        f'=== CURRENT TASK ===\n'
        f'Trigger type: {trigger_type}\n'
        f'Context: {trigger_context}\n\n'
        f'Execute your responsibilities. Use your tools. Report clearly what you did and found.'
    )

    # Build tools
    tools = build_tools(de_name)

    # Create WorkSession (loads the existing session file)
    try:
        from work_session import WorkSession
        session = WorkSession.load(de_name, session_id)
    except Exception as e:
        print(f'[session_runner] WorkSession load failed: {e} — continuing without session tracking')
        session = None

    # Choose engine: prefer OpenClaw gateway (always valid), fallback to direct Anthropic
    use_openai_engine = bool(os.environ.get('OPENCLAW_GATEWAY_TOKEN', '').strip())

    if use_openai_engine:
        try:
            from react_engine_openai import ReActEngineOpenAI as EngineClass
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from react_engine_openai import ReActEngineOpenAI as EngineClass
        print('[session_runner] Engine: OpenAI-compat (OpenClaw gateway)')
    else:
        try:
            from react_engine import ReActEngine as EngineClass
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from react_engine import ReActEngine as EngineClass
        print('[session_runner] Engine: Anthropic direct')

    model = os.environ.get('DE_MODEL', 'claude-sonnet-4-6')
    print(f'[session_runner] Model hint: {model}')

    engine = EngineClass(
        agent_name=de_name,
        mission=mission,
        tools=tools,
        max_iterations=8,
        model=model,
        session=session,
    )

    try:
        result = engine.run()
        status = result.get('status', 'complete')
        summary = result.get('summary') or f'Completed in {result.get("iterations", 0)} iterations.'

        # Update session file
        session_raw_updated = json.loads(session_file.read_text())
        session_raw_updated['status'] = 'done' if status == 'complete' else status
        session_raw_updated['completed_at'] = _now()
        session_raw_updated['result'] = summary
        session_file.write_text(json.dumps(session_raw_updated, indent=2))

        status_emoji = {'complete': '✅', 'human_decision_needed': '⏳', 'max_iterations_reached': '🔄'}.get(status, 'ℹ️')
        write_portal_inbox(
            de_name,
            title=f'{status_emoji} {display_name}: session {status}',
            body=summary[:500],
        )
        print(f'[session_runner] Done: {status}')

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f'[session_runner] FATAL ERROR: {e}\n{tb}')
        session_raw_updated = json.loads(session_file.read_text())
        session_raw_updated['status'] = 'error'
        session_raw_updated['error'] = str(e)
        session_raw_updated['completed_at'] = _now()
        session_file.write_text(json.dumps(session_raw_updated, indent=2))
        write_portal_inbox(de_name, title=f'❌ {display_name}: error', body=str(e), level=2)
        sys.exit(1)


if __name__ == '__main__':
    main()
