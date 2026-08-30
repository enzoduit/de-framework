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


def _generate_job_md(p: dict) -> str:
    """Generate a job.md from Create DE form payload."""
    name = p.get('display_name') or p.get('name', 'AGENT')
    role = p.get('role', '')
    mission = p.get('mission', 'No mission defined yet.')
    kpis = p.get('kpis', [])
    resp = p.get('responsibilities', {})
    l0 = resp.get('level_0', [])
    l1 = resp.get('level_1', [])
    l2 = resp.get('level_2', [])
    constraints = p.get('hard_constraints', [])
    eval_data = p.get('self_evaluation', {})
    criteria = eval_data.get('criteria', [])
    schedule = eval_data.get('schedule', 'manual')
    sources = p.get('data_sources', [])
    autoresearch = p.get('autoresearch', {})
    research_enabled = autoresearch.get('enabled', False)
    research_queries = autoresearch.get('queries', [])
    research_freq = autoresearch.get('schedule', 'daily')

    lines = []
    lines.append(f'# {name} — {role}')
    lines.append('')
    lines.append('## Mission')
    lines.append(mission)
    lines.append('')

    if kpis:
        lines.append('## KPIs')
        for k in kpis:
            lines.append(f'- {k}')
        lines.append('')

    lines.append('## Autonomy Levels')
    lines.append('')
    lines.append('### Level 0 — Act immediately, no notification')
    if l0:
        for item in l0:
            lines.append(f'- {item}')
    else:
        lines.append('- Read own state files (metrics.json, memory.md, log.jsonl)')
    lines.append('')

    lines.append('### Level 1 — Act, then document (reversible)')
    if l1:
        for item in l1:
            lines.append(f'- {item}')
    else:
        lines.append('- (None defined)')
    lines.append('')

    lines.append('### Level 2 — Requires explicit approval before acting')
    if l2:
        for item in l2:
            lines.append(f'- {item}')
    else:
        lines.append('- (None defined)')
    lines.append('')

    if constraints:
        lines.append('## Hard Constraints')
        for c in constraints:
            lines.append(f'- {c}')
        lines.append('')

    if criteria:
        lines.append('## Self-Evaluation Criteria')
        lines.append(f'Run schedule: {schedule}')
        lines.append('')
        lines.append('After each run, evaluate yourself against these criteria and update metrics.json:')
        for c in criteria:
            lines.append(f'- {c}')
        lines.append('')

    if sources:
        lines.append('## Data Sources')
        for s in sources:
            lines.append(f'- {s}')
        lines.append('')

    if research_enabled and research_queries:
        lines.append('## Autoresearch')
        lines.append(f'Frequency: {research_freq}')
        lines.append('')
        lines.append('On each research run, search for and summarize findings on these topics, then append key insights to memory.md:')
        for q in research_queries:
            lines.append(f'- {q}')
        lines.append('')

    lines.append('## Instructions')
    lines.append('1. Start by reading your current state: metrics.json, memory.md, and recent log entries.')
    lines.append('2. Perform your regular duties appropriate to the trigger type.')
    lines.append('3. Document findings using write_portal_inbox for anything noteworthy.')
    lines.append('4. Update metrics.json with current KPI values using update_metrics.')
    lines.append('5. Evaluate yourself against your success criteria. Record the result in metrics.json.')
    lines.append('6. For Level 2 actions, call request_human_decision and pause.')
    lines.append('7. End with a clear summary of what you did and what the current state is.')
    lines.append('')
    lines.append('Be specific and action-oriented. Verify changes worked before declaring success.')

    return '\n'.join(lines)


def handle_de_create(handler, body: dict):
    """POST /de/create — create a new Digital Employee from form payload."""
    name = (body.get('name') or '').strip().lower().replace(' ', '-')
    if not name:
        return handler.send_json(400, {'ok': False, 'error': 'name is required'})
    if not name.replace('-', '').isalnum():
        return handler.send_json(400, {'ok': False, 'error': 'name must be lowercase alphanumeric with hyphens only'})

    de_dir = AGENTS_BASE / name
    if de_dir.exists():
        return handler.send_json(409, {'ok': False, 'error': f'Agent "{name}" already exists'})

    try:
        de_dir.mkdir(parents=True)
        (de_dir / 'sessions').mkdir()

        # de.json — agent profile
        de_json = {
            'name': name,
            'display_name': body.get('display_name') or name.upper(),
            'role': body.get('role', ''),
            'color': body.get('color', '#FF4500'),
            'mission': body.get('mission', ''),
            'kpis': body.get('kpis', []),
            'responsibilities': body.get('responsibilities', {'level_0': [], 'level_1': [], 'level_2': []}),
            'hard_constraints': body.get('hard_constraints', []),
            'data_sources': body.get('data_sources', []),
            'self_evaluation': body.get('self_evaluation', {}),
            'autoresearch': body.get('autoresearch', {}),
            'triggers': [
                {'type': 'user', 'description': 'On-demand via portal or API'},
            ],
        }
        schedule = (body.get('self_evaluation') or {}).get('schedule', 'manual')
        if schedule and schedule != 'manual':
            schedule_labels = {
                'hourly': 'Every hour',
                '3x_daily': '3x daily (08:00, 14:00, 20:00 UTC)',
                'daily': 'Daily at 08:00 UTC',
                'weekly': 'Weekly on Monday at 08:00 UTC',
            }
            de_json['triggers'].append({
                'type': 'cron',
                'schedule': schedule_labels.get(schedule, schedule),
                'description': 'Scheduled autonomous run',
            })

        (de_dir / 'de.json').write_text(json.dumps(de_json, indent=2))

        # job.md — generated mission brief
        job_md = _generate_job_md(body)
        (de_dir / 'job.md').write_text(job_md)

        # metrics.json — empty initial state
        (de_dir / 'metrics.json').write_text(json.dumps({
            'created_at': now_iso(),
            'last_updated': now_iso(),
        }, indent=2))

        # memory.md — empty
        (de_dir / 'memory.md').write_text(f'# {de_json["display_name"]} — Memory\n\nCreated {now_iso()}. No entries yet.\n')

        return handler.send_json(201, {'ok': True, 'name': name, 'dir': str(de_dir)})
    except Exception as e:
        # clean up on failure
        import shutil
        try: shutil.rmtree(de_dir)
        except Exception: pass
        return handler.send_json(500, {'ok': False, 'error': str(e)})


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
