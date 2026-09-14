"""
Tool implementations for the DE Framework ReAct engine.

Each tool is a dict with:
  name        — tool id (matches de.json tools array)
  description — shown to Claude
  input_schema — Anthropic-format JSON schema
  fn          — Python callable(input_dict) → str | dict
"""

import json
import os
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path('/var/de-agents')
CUSTOM_TOOLS_DIR = Path(os.environ.get('CUSTOM_TOOLS_DIR', '/var/de-framework-tools'))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ─── exec_shell ──────────────────────────────────────────────────────────────

def _exec_shell(inp: dict) -> dict:
    cmd = inp.get('command', '').strip()
    if not cmd:
        return {'error': 'command is required'}
    timeout = min(int(inp.get('timeout', 30)), 120)
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd='/root'
        )
        out = (result.stdout or '') + (result.stderr or '')
        out = out[:4000]  # truncate
        return {'exit_code': result.returncode, 'output': out}
    except subprocess.TimeoutExpired:
        return {'error': f'Command timed out after {timeout}s'}
    except Exception as e:
        return {'error': str(e)}


# ─── read_file ───────────────────────────────────────────────────────────────

def _read_file(inp: dict) -> dict:
    path_str = inp.get('path', '').strip()
    if not path_str:
        return {'error': 'path is required'}
    path = Path(path_str)
    if not path.exists():
        return {'error': f'File not found: {path_str}'}
    if not path.is_file():
        return {'error': f'Not a file: {path_str}'}
    try:
        content = path.read_text(errors='replace')
        max_chars = int(inp.get('max_chars', 8000))
        truncated = len(content) > max_chars
        return {
            'content': content[:max_chars],
            'truncated': truncated,
            'size': len(content),
        }
    except Exception as e:
        return {'error': str(e)}


# ─── write_file ──────────────────────────────────────────────────────────────

def _write_file(inp: dict) -> dict:
    path_str = inp.get('path', '').strip()
    content = inp.get('content', '')
    if not path_str:
        return {'error': 'path is required'}
    path = Path(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {'ok': True, 'path': str(path), 'bytes': len(content)}
    except Exception as e:
        return {'error': str(e)}


# ─── send_telegram ───────────────────────────────────────────────────────────

def _send_telegram(inp: dict) -> dict:
    message = inp.get('message', '').strip()
    if not message:
        return {'error': 'message is required'}

    # Load bot token from openclaw config
    try:
        cfg = json.loads(Path('/root/.openclaw/openclaw.json').read_text())
        bot_token = cfg['telegram']['accounts'][0]['botToken']
    except Exception as e:
        return {'error': f'Cannot load bot token: {e}'}

    chat_id = inp.get('chat_id', -1003728024208)
    thread_id = inp.get('thread_id', 7694)

    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
    }
    if thread_id:
        payload['message_thread_id'] = thread_id

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return {'ok': True, 'status': resp.status}
    except Exception as e:
        return {'error': str(e)}


# ─── web_search ──────────────────────────────────────────────────────────────

def _web_search(inp: dict) -> dict:
    query = inp.get('query', '').strip()
    url = inp.get('url', '').strip()

    if url:
        # Fetch specific URL
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=15)
            content = resp.read().decode('utf-8', errors='replace')
            # Strip HTML tags roughly
            import re
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()
            return {'url': url, 'content': content[:5000]}
        except Exception as e:
            return {'error': str(e)}

    if query:
        # Use DuckDuckGo instant answer API
        try:
            encoded = urllib.parse.quote(query)
            api_url = f'https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1'
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            abstract = data.get('AbstractText', '')
            answer = data.get('Answer', '')
            results = []
            for r in data.get('RelatedTopics', [])[:5]:
                if isinstance(r, dict) and r.get('Text'):
                    results.append({'text': r['Text'], 'url': r.get('FirstURL', '')})
            return {
                'query': query,
                'abstract': abstract,
                'answer': answer,
                'results': results,
            }
        except Exception as e:
            return {'error': str(e)}

    return {'error': 'query or url is required'}


# ─── schedule_next_session ───────────────────────────────────────────────────

def _schedule_next_session(inp: dict) -> dict:
    """Write a one-time scheduled session entry for this agent."""
    de_name = inp.get('de_name', '').strip()
    prompt = inp.get('prompt', '').strip()
    run_at = inp.get('run_at', '').strip()  # ISO datetime UTC

    if not de_name or not prompt:
        return {'error': 'de_name and prompt are required'}

    sched_file = AGENTS_DIR / de_name / 'schedule.json'
    try:
        if sched_file.exists():
            data = json.loads(sched_file.read_text())
        else:
            data = {'activities': [], 'schedules': [], 'updated_at': _now_iso()}

        import uuid
        entry = {
            'id': f'one-time-{uuid.uuid4().hex[:8]}',
            'name': f'One-time: {prompt[:40]}',
            'active': True,
            'frequency': 'once',
            'run_at': run_at or _now_iso(),
            'prompt': prompt,
            'created_at': _now_iso(),
        }
        data.setdefault('schedules', []).append(entry)
        data['updated_at'] = _now_iso()
        sched_file.write_text(json.dumps(data, indent=2))
        return {'ok': True, 'scheduled': entry}
    except Exception as e:
        return {'error': str(e)}


# ─── report_to_colleague ─────────────────────────────────────────────────────

def _report_to_colleague(inp: dict) -> dict:
    """Write a report/reply to another DE's inbox."""
    colleague = inp.get('colleague', '').lower().strip()
    report = inp.get('report', inp.get('message', '')).strip()
    context = inp.get('context', '')

    if not colleague or not report:
        return {'error': 'colleague and report are required'}

    inbox = AGENTS_DIR / colleague / 'inbox.jsonl'
    inbox.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        'ts': _now_iso(),
        'type': 'report',
        'from': inp.get('from_de', 'unknown'),
        'message': report,
        'context': context,
        'status': 'unread',
    }
    with open(inbox, 'a') as f:
        f.write(json.dumps(entry) + '\n')

    return {'ok': True, 'delivered_to': colleague}


# ─── Tool Library ─────────────────────────────────────────────────────────────

TOOL_LIBRARY = {
    'exec_shell': {
        'name': 'exec_shell',
        'description': 'Run a shell command on the server and return the output. Use for system checks, file operations, service management.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'command': {'type': 'string', 'description': 'Shell command to run'},
                'timeout': {'type': 'integer', 'description': 'Timeout in seconds (max 120)', 'default': 30},
            },
            'required': ['command'],
        },
        'fn': _exec_shell,
    },
    'read_file': {
        'name': 'read_file',
        'description': 'Read a file from the server filesystem.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Absolute or relative file path'},
                'max_chars': {'type': 'integer', 'description': 'Max characters to return (default 8000)'},
            },
            'required': ['path'],
        },
        'fn': _read_file,
    },
    'write_file': {
        'name': 'write_file',
        'description': 'Write content to a file on the server filesystem.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'File path to write'},
                'content': {'type': 'string', 'description': 'Content to write'},
            },
            'required': ['path', 'content'],
        },
        'fn': _write_file,
    },
    'send_telegram': {
        'name': 'send_telegram',
        'description': 'Send a Telegram message to the team channel. Use for important updates, alerts, or reports.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': 'Message text (HTML allowed)'},
                'chat_id': {'type': 'integer', 'description': 'Telegram chat ID (default: team group)'},
                'thread_id': {'type': 'integer', 'description': 'Topic/thread ID (default: ops topic)'},
            },
            'required': ['message'],
        },
        'fn': _send_telegram,
    },
    'web_search': {
        'name': 'web_search',
        'description': 'Search the web or fetch a URL. For research, status checks, or external data.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Search query'},
                'url': {'type': 'string', 'description': 'Fetch a specific URL instead of searching'},
            },
        },
        'fn': _web_search,
    },
    'schedule_next_session': {
        'name': 'schedule_next_session',
        'description': 'Schedule a follow-up session for yourself or another DE at a specific time.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'de_name': {'type': 'string', 'description': 'DE name to schedule (e.g. ops, growth)'},
                'prompt': {'type': 'string', 'description': 'What the session should do'},
                'run_at': {'type': 'string', 'description': 'ISO datetime UTC when to run'},
            },
            'required': ['de_name', 'prompt'],
        },
        'fn': _schedule_next_session,
    },
    'ask_colleague': {
        'name': 'ask_colleague',
        'description': 'Send a question or request to another digital employee. They will respond in their next session.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'colleague': {'type': 'string', 'description': 'DE name to ask (e.g. growth, max, scribe)'},
                'message': {'type': 'string', 'description': 'Your question or request'},
                'context': {'type': 'string', 'description': 'Additional context'},
            },
            'required': ['colleague', 'message'],
        },
        # fn is registered by react_engine._register_ask_colleague_tool
    },
    'report_to_colleague': {
        'name': 'report_to_colleague',
        'description': 'Send a report or update to another digital employee (e.g. status report to your manager).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'colleague': {'type': 'string', 'description': 'DE name to report to'},
                'report': {'type': 'string', 'description': 'Your report or update'},
                'context': {'type': 'string', 'description': 'Additional context'},
            },
            'required': ['colleague', 'report'],
        },
        'fn': _report_to_colleague,
    },
    'request_human_decision': {
        'name': 'request_human_decision',
        'description': 'Request a human decision for actions that require approval. Use when you cannot proceed autonomously.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string', 'description': 'Short decision title (max 80 chars)'},
                'description': {'type': 'string', 'description': 'What needs to be decided and why'},
                'proposed_action': {'type': 'string', 'description': 'What you propose to do'},
                'options': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'List of options for the human to choose from',
                },
            },
            'required': ['title', 'description', 'proposed_action'],
        },
        # fn is registered by react_engine._register_human_decision_tool
    },
    'write_metric': {
        'name': 'write_metric',
        'description': 'Record a KPI metric value for this DE. Call at end of session for each KPI you measured.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'kpi_id': {'type': 'string', 'description': 'KPI id from de.json kpis array'},
                'value': {'type': 'number', 'description': 'Current measured value'},
                'notes': {'type': 'string', 'description': 'Brief note on how you measured this'},
            },
            'required': ['kpi_id', 'value'],
        },
        # fn is registered by react_engine._register_write_metric_tool
    },
}


# ─── Custom tool support ─────────────────────────────────────────────────────

def _decrypt_credentials(required_creds: list) -> tuple[dict, list]:
    """
    Decrypt required credentials and return (env_dict, missing_ids).
    env_dict maps credential id → decrypted value (ready for subprocess env).
    missing_ids lists any credentials that could not be decrypted.
    """
    from backend.routes.creds_routes import decrypt_credential, update_last_used
    env_vals = {}
    missing = []
    for cred_id in required_creds:
        value = decrypt_credential(cred_id)
        if value is None:
            # Fallback: use existing system environment variable if available.
            # This means scripts that already work on the server (credentials in
            # /etc/de-framework.env or the system env) work transparently as DE
            # tools without requiring re-entry in the portal.
            env_fallback = os.environ.get(cred_id)
            if env_fallback:
                env_vals[cred_id] = env_fallback
            else:
                missing.append(cred_id)
        else:
            env_vals[cred_id] = value
            update_last_used(cred_id)
    return env_vals, missing


def make_custom_tool_fn(script: str, script_args: list = None, required_credentials: list = None):
    """
    Factory: returns a callable that runs a custom script as a tool.

    Execution model:
      - Static argv: [script] + script_args (e.g. ["/usr/bin/bash", "-c", "..."])
      - Per-call args: each key in the input dict is exported as ARG_<KEY>=<value>
      - Credentials: each required credential is decrypted and injected as an env var
      - Output: {exit_code, output} mirroring exec_shell
    """
    _args = list(script_args or [])
    _required_creds = list(required_credentials or [])

    def _fn(inp: dict) -> dict:
        import os as _os
        env = dict(_os.environ)
        # Inject required credentials as env vars (decrypted — never logged)
        if _required_creds:
            cred_vals, missing = _decrypt_credentials(_required_creds)
            if missing:
                return {
                    'error': f'Missing credential(s): {", ".join(missing)}. '
                             f'Set them in the portal under Tool Library → 🔑 Credentials.'
                }
            env.update(cred_vals)
        # Pass input dict as env vars (ARG_DATE=..., ARG_QUERY=..., etc.)
        for k, v in (inp or {}).items():
            env[f'ARG_{k.upper()}'] = str(v)
        cmd = [script] + _args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=120, cwd='/root', env=env,
            )
            out = (result.stdout or '') + (result.stderr or '')
            return {'exit_code': result.returncode, 'output': out[:4000]}
        except subprocess.TimeoutExpired:
            return {'error': 'Custom tool timed out after 120s'}
        except FileNotFoundError:
            return {'error': f'Script not found: {script}'}
        except Exception as e:
            return {'error': str(e)}

    return _fn



# ─── RL Loop tools ───────────────────────────────────────────────────────────

def _log_assumption(inp: dict) -> dict:
    """Log an assumed outcome after taking an action — starts the RL measurement loop."""
    import uuid as _uuid
    from datetime import datetime, timedelta
    agent_name = inp.get('_agent_name', '')
    action = inp.get('action', '').strip()
    expected_outcome = inp.get('expected_outcome', '').strip()
    metric = inp.get('metric', '').strip()
    check_after_days = max(1, int(inp.get('check_after_days', 3)))
    if not agent_name:
        return {'error': 'agent context missing'}
    if not action or not expected_outcome:
        return {'error': 'action and expected_outcome are required'}
    workspace = AGENTS_DIR / agent_name / 'workspace'
    workspace.mkdir(exist_ok=True)
    af = workspace / 'assumptions.json'
    try:
        data = json.loads(af.read_text()) if af.exists() else []
    except Exception:
        data = []
    assumption_id = _uuid.uuid4().hex[:8]
    check_date = (datetime.now() + timedelta(days=check_after_days)).strftime('%Y-%m-%d')
    data.append({
        'id': assumption_id,
        'created_at': datetime.now().isoformat(),
        'action': action,
        'expected_outcome': expected_outcome,
        'metric': metric,
        'check_after_days': check_after_days,
        'check_date': check_date,
        'status': 'pending',
    })
    af.write_text(json.dumps(data, indent=2))
    return {'ok': True, 'assumption_id': assumption_id, 'check_date': check_date,
            'message': f'Assumption logged — check back on {check_date} (id: {assumption_id})'}


def _measure_assumption(inp: dict) -> dict:
    """Record the measurement result for a pending assumption. Closes the RL loop."""
    from datetime import datetime
    agent_name = inp.get('_agent_name', '')
    assumption_id = inp.get('assumption_id', '').strip()
    actual_result = inp.get('actual_result', '').strip()
    reward = inp.get('reward', '').strip()
    note = inp.get('note', '').strip()
    if not agent_name:
        return {'error': 'agent context missing'}
    if not actual_result or reward not in ('reward', 'disreward'):
        return {'error': 'actual_result required; reward must be "reward" or "disreward"'}
    workspace = AGENTS_DIR / agent_name / 'workspace'
    af = workspace / 'assumptions.json'
    try:
        data = json.loads(af.read_text()) if af.exists() else []
    except Exception:
        return {'error': 'Could not read assumptions.json'}
    target = None
    for a in data:
        if a.get('status') == 'pending':
            if not assumption_id or a.get('id') == assumption_id:
                target = a
                break
    if not target:
        return {'error': f'No pending assumption found' + (f' with id: {assumption_id}' if assumption_id else '')}
    now = datetime.now()
    target.update({'status': 'measured', 'measured_at': now.isoformat(),
                   'actual_result': actual_result, 'reward': reward, 'note': note})
    af.write_text(json.dumps(data, indent=2))
    # Write to LEARNING_LOG.md
    log = workspace / 'LEARNING_LOG.md'
    today = now.strftime('%Y-%m-%d')
    emoji = '✅' if reward == 'reward' else '❌'
    label = '[+REWARD]' if reward == 'reward' else '[-DISREWARD]'
    entry = f'\n## [{today}] {target["action"]}\n'
    entry += f'**Expected:** {target["expected_outcome"]}\n'
    entry += f'**Actual:** {actual_result}\n'
    if note:
        entry += f'**Note:** {note}\n'
    entry += f'**Result:** {emoji} {label}\n'
    if not log.exists():
        log.write_text(f'# LEARNING_LOG\u2014{agent_name.upper()}\n\nAssumption-measure cycles. [+REWARD]=confirmed, [-DISREWARD]=no impact.\n')
    with open(log, 'a') as f:
        f.write(entry)
    return {'ok': True, 'reward': reward, 'logged': True,
            'message': f'{emoji} {label} logged to LEARNING_LOG.md'}


TOOL_LIBRARY['log_assumption'] = {
    'name': 'log_assumption',
    'description': 'After taking an action, log the expected outcome and when to check it. Part of the autonomous RL learning loop.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'action': {'type': 'string', 'description': 'What action you just took'},
            'expected_outcome': {'type': 'string', 'description': 'What outcome you expect and why'},
            'metric': {'type': 'string', 'description': 'How to measure success (e.g. check website visitors, geo ranking for keyword X)'},
            'check_after_days': {'type': 'integer', 'description': 'Days until you check the result (default: 3)', 'default': 3},
        },
        'required': ['action', 'expected_outcome'],
    },
    'fn': _log_assumption,
}

TOOL_LIBRARY['measure_assumption'] = {
    'name': 'measure_assumption',
    'description': 'Record the measurement result for a pending assumption. Close the RL loop with a reward or disreward.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'assumption_id': {'type': 'string', 'description': 'ID from log_assumption (empty = oldest pending)'},
            'actual_result': {'type': 'string', 'description': 'What actually happened when you measured'},
            'reward': {'type': 'string', 'description': '"reward" if expected outcome achieved, "disreward" if not', 'enum': ['reward', 'disreward']},
            'note': {'type': 'string', 'description': 'What you learned and will do differently'},
        },
        'required': ['actual_result', 'reward'],
    },
    'fn': _measure_assumption,
}


def _load_and_register_custom_tools() -> None:
    """
    Scan CUSTOM_TOOLS_DIR for *.json definitions and inject each into TOOL_LIBRARY.
    Called once at module init; re-importing the module (in session_runner subprocess)
    will pick up any tools registered since the server started.
    """
    if not CUSTOM_TOOLS_DIR.exists():
        return
    for f in sorted(CUSTOM_TOOLS_DIR.glob('*.json')):
        try:
            data = json.loads(f.read_text())
            tool_id = (data.get('id') or '').strip()
            script   = (data.get('script') or '').strip()
            if not tool_id or not script:
                continue
            schema = data.get('args_schema') or {}
            if not schema.get('type'):
                schema = {'type': 'object', 'properties': {}}
            required_creds = data.get('required_credentials', [])
            TOOL_LIBRARY[tool_id] = {
                'name':                 tool_id,
                'description':          data.get('description', f'Custom tool: {tool_id}'),
                'input_schema':         schema,
                'fn':                   make_custom_tool_fn(script, data.get('script_args', []), required_creds),
                'source':               'custom',
                'required_credentials': required_creds,
            }
        except Exception as e:
            print(f'[tool_implementations] Could not load custom tool {f.name}: {e}')


def get_tool_defs(tool_ids: list) -> list:
    """
    Convert a list of tool ID strings (from de.json) to full tool dicts
    suitable for passing to ReActEngine.
    Unknown IDs are skipped with a warning.
    """
    result = []
    for tid in tool_ids:
        if isinstance(tid, dict):
            # Already a full dict — pass through
            result.append(tid)
        elif isinstance(tid, str):
            defn = TOOL_LIBRARY.get(tid)
            if defn:
                result.append(defn)
            else:
                print(f'[tool_implementations] Unknown tool id: {tid!r} — skipping')
        else:
            print(f'[tool_implementations] Unexpected tool entry type: {type(tid)} — skipping')
    return result


# ─── Register custom tools at module init ────────────────────────────────────
# Runs when the module is first imported (server startup and each session_runner
# subprocess). Picks up any *.json files already in CUSTOM_TOOLS_DIR.
_load_and_register_custom_tools()
