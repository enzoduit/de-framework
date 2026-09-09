"""
DE Routes — /de-list, /de/<name>, /de/<name>/sessions, /de/<name>/sessions/<id>
"""

import json
import subprocess as _sp
import uuid as _uuid
from datetime import datetime, timedelta, timezone as _tz
from pathlib import Path
from backend.config import AGENTS_BASE, DE_NAMES, now_iso
from backend.core.tool_discovery import get_tools as _get_tools, REQUIRED_TOOL_IDS

CUSTOM_TOOLS_DIR = Path('/var/de-framework-tools')

# session_runner.py lives in backend/core/
_BACKEND_DIR = Path(__file__).parent.parent  # backend/


def _compute_next_run(frequency: str, time_utc: str = '08:00') -> str:
    """Compute the next ISO datetime for a given frequency and UTC time."""
    h, m = 8, 0
    if ':' in time_utc:
        try: h, m = map(int, time_utc.split(':'))
        except: pass
    now = datetime.now(_tz.utc)
    candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _compute_next_run_from_schedule(s: dict) -> str:
    """Compute next run ISO datetime from a schedule dict (with frequency, time_utc, days)."""
    frequency = s.get('frequency', 'daily')
    time_utc = s.get('time_utc', '08:00')
    days = s.get('days', ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])

    h, m = 8, 0
    if ':' in time_utc:
        try: h, m = map(int, time_utc.split(':'))
        except: pass

    now = datetime.now(_tz.utc)
    DAY_MAP = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}

    if frequency == 'daily':
        allowed_days = list(range(7))
    elif frequency == 'weekdays':
        allowed_days = [0, 1, 2, 3, 4]
    elif frequency == 'weekly':
        allowed_days = [DAY_MAP[d] for d in (days[:1] if days else ['mon']) if d in DAY_MAP]
    else:  # custom
        allowed_days = [DAY_MAP[d] for d in days if d in DAY_MAP]

    if not allowed_days:
        allowed_days = list(range(7))

    candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
    for i in range(8):
        check = candidate + timedelta(days=i)
        if check > now and check.weekday() in allowed_days:
            return check.isoformat()

    return (candidate + timedelta(days=1)).isoformat()


def _start_session_for_schedule(de_name: str, schedule: dict) -> str:
    """Create and spawn a session for a scheduled entry. Returns session_id."""
    sessions_dir = AGENTS_BASE / de_name / 'sessions'
    sessions_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(_tz.utc).strftime('%Y%m%d-%H%M%S')
    short = _uuid.uuid4().hex[:6]
    session_id = f'ws-{de_name}-{ts}-{short}'

    prompt = schedule.get('prompt', 'Scheduled run')

    session_data = {
        'id': session_id,
        'de': de_name,
        'trigger_type': 'scheduled',
        'trigger_from': 'scheduler',
        'trigger_context': prompt,
        'schedule_id': schedule.get('id'),
        'schedule_name': schedule.get('name'),
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

    # Write to inbox
    inbox_file = AGENTS_BASE / de_name / 'inbox.jsonl'
    inbox_entry = {
        'type': 'scheduled_trigger',
        'session_id': session_id,
        'context': prompt,
        'trigger_type': 'scheduled',
        'schedule_id': schedule.get('id'),
        'ts': now_iso(),
    }
    with open(inbox_file, 'a') as f:
        f.write(json.dumps(inbox_entry) + '\n')

    # Spawn session_runner
    _SESSION_RUNNER = _BACKEND_DIR / 'core' / 'session_runner.py'
    _log = f'/tmp/session-{de_name}-{session_id}.log'
    _sp.Popen(
        ['python3', str(_SESSION_RUNNER), de_name, session_id],
        stdout=open(_log, 'w'),
        stderr=_sp.STDOUT,
        cwd=str(_BACKEND_DIR.parent),
    )
    return session_id


def handle_de_schedule_get(handler, de_name: str):
    """GET /de/<name>/schedule"""
    schedule_file = AGENTS_BASE / de_name / 'schedule.json'
    if not schedule_file.exists():
        return handler.send_json(200, {'activities': [], 'schedules': [], 'de': de_name})
    try:
        data = json.loads(schedule_file.read_text())
        data.setdefault('activities', [])
        data.setdefault('schedules', [])
        return handler.send_json(200, data)
    except Exception:
        return handler.send_json(200, {'activities': [], 'schedules': [], 'de': de_name})


def handle_de_schedule_post(handler, de_name: str, body: dict):
    """POST /de/<name>/schedule — create a new schedule entry.
    If body has 'prompt' field → human-configured schedule (stored in 'schedules' array).
    If body has 'trigger_context' field → agent activity (stored in 'activities' array).
    """
    schedule_file = AGENTS_BASE / de_name / 'schedule.json'
    try:
        schedule = json.loads(schedule_file.read_text()) if schedule_file.exists() else {}
    except Exception:
        schedule = {}
    schedule.setdefault('activities', [])
    schedule.setdefault('schedules', [])

    if 'prompt' in body:
        # Human-configured recurring schedule
        sched_id = 'sched-' + _uuid.uuid4().hex[:8]
        entry = {
            'id': sched_id,
            'name': body.get('name', 'Scheduled Run'),
            'active': body.get('active', True),
            'frequency': body.get('frequency', 'daily'),
            'time_utc': body.get('time_utc', '08:00'),
            'days': body.get('days', ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']),
            'prompt': body.get('prompt', ''),
            'next_run': _compute_next_run_from_schedule(body),
            'last_run': None,
            'last_session_id': None,
            'created_at': now_iso(),
        }
        schedule['schedules'].append(entry)
        schedule['updated_at'] = now_iso()
        schedule_file.write_text(json.dumps(schedule, indent=2))
        return handler.send_json(201, {'ok': True, 'schedule': entry})
    else:
        # Agent-created activity (backward compat)
        activity = {
            'id': _uuid.uuid4().hex[:8],
            'title': body.get('title', 'Scheduled activity'),
            'frequency': body.get('frequency', 'once'),
            'time_utc': body.get('time_utc', '08:00'),
            'trigger_context': body.get('trigger_context', ''),
            'created_by': body.get('created_by', 'user'),
            'last_run_at': None,
            'next_run_at': body.get('next_run_at') or _compute_next_run(
                body.get('frequency', 'once'), body.get('time_utc', '08:00')
            ),
            'run_count': 0,
        }
        existing_id = body.get('id')
        activities = schedule['activities']
        if existing_id:
            for i, a in enumerate(activities):
                if a.get('id') == existing_id:
                    activities[i] = {**a, **activity, 'id': existing_id, 'run_count': a.get('run_count', 0)}
                    break
            else:
                activities.append(activity)
        else:
            activities.append(activity)
        schedule['updated_at'] = now_iso()
        schedule_file.write_text(json.dumps(schedule, indent=2))
        return handler.send_json(201, {'ok': True, 'activity': activity})


def handle_schedule_update(handler, de_name: str, sched_id: str, body: dict):
    """PATCH /de/<name>/schedule/<id> — update a human-configured schedule."""
    schedule_file = AGENTS_BASE / de_name / 'schedule.json'
    if not schedule_file.exists():
        return handler.send_json(404, {'error': 'No schedule file'})
    try:
        data = json.loads(schedule_file.read_text())
    except Exception:
        return handler.send_json(500, {'error': 'Could not read schedule file'})
    schedules = data.get('schedules', [])
    for s in schedules:
        if s.get('id') == sched_id:
            for field in ['name', 'active', 'frequency', 'time_utc', 'days', 'prompt']:
                if field in body:
                    s[field] = body[field]
            # Recompute next_run if schedule parameters changed
            if any(f in body for f in ['frequency', 'time_utc', 'days']):
                s['next_run'] = _compute_next_run_from_schedule(s)
            data['updated_at'] = now_iso()
            schedule_file.write_text(json.dumps(data, indent=2))
            return handler.send_json(200, {'ok': True, 'schedule': s})
    return handler.send_json(404, {'error': f'Schedule {sched_id} not found'})


def handle_schedule_delete(handler, de_name: str, sched_id: str):
    """DELETE /de/<name>/schedule/<id> — remove a human-configured schedule."""
    schedule_file = AGENTS_BASE / de_name / 'schedule.json'
    if not schedule_file.exists():
        return handler.send_json(404, {'error': 'No schedule file'})
    try:
        data = json.loads(schedule_file.read_text())
    except Exception:
        return handler.send_json(500, {'error': 'Could not read schedule file'})
    schedules = data.get('schedules', [])
    new_schedules = [s for s in schedules if s.get('id') != sched_id]
    if len(new_schedules) == len(schedules):
        return handler.send_json(404, {'error': f'Schedule {sched_id} not found'})
    data['schedules'] = new_schedules
    data['updated_at'] = now_iso()
    schedule_file.write_text(json.dumps(data, indent=2))
    return handler.send_json(200, {'ok': True})


def handle_trigger_scheduled(handler):
    """GET /trigger-scheduled — check all DEs, trigger overdue schedules (called by cron)."""
    triggered = []
    now = datetime.now(_tz.utc)
    for de_name in _get_de_names():
        sched_file = AGENTS_BASE / de_name / 'schedule.json'
        if not sched_file.exists():
            continue
        try:
            data = json.loads(sched_file.read_text())
        except Exception:
            continue
        schedules = data.get('schedules', [])
        changed = False
        for s in schedules:
            if not s.get('active', True):
                continue
            next_run = s.get('next_run')
            if not next_run:
                continue
            try:
                next_run_dt = datetime.fromisoformat(next_run.replace('Z', '+00:00'))
            except Exception:
                continue
            if next_run_dt <= now:
                try:
                    session_id = _start_session_for_schedule(de_name, s)
                    s['last_run'] = now.isoformat()
                    s['last_session_id'] = session_id
                    s['next_run'] = _compute_next_run_from_schedule(s)
                    changed = True
                    triggered.append({'de': de_name, 'sched_id': s['id'], 'session_id': session_id})
                except Exception as e:
                    triggered.append({'de': de_name, 'sched_id': s['id'], 'error': str(e)})
        if changed:
            sched_file.write_text(json.dumps(data, indent=2))
    return handler.send_json(200, {'ok': True, 'triggered': triggered, 'count': len(triggered)})


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


def _calc_duration(d):
    try:
        from datetime import datetime, timezone
        start = d.get('started_at') or d.get('created_at')
        end = d.get('completed_at')
        if start and end:
            s = datetime.fromisoformat(start.replace('Z', '+00:00'))
            e = datetime.fromisoformat(end.replace('Z', '+00:00'))
            return round((e - s).total_seconds())
    except Exception:
        pass
    return None


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
                'duration_seconds': _calc_duration(d),
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
    lines.append('')
    lines.append('## Scheduling your next activity')
    lines.append('Use the **schedule_next_activity** tool to plan your next session. Call it when:')
    lines.append('- You find something that needs follow-up (e.g. fixed a bug → schedule a check that it held)')
    lines.append('- A task is too large for one session → schedule the next step')
    lines.append('- You want to establish a recurring pattern beyond your default schedule')
    lines.append('Always include specific questions in the trigger_context so future-you knows exactly what to focus on.')

    # Work schedule
    schedule_entries = p.get('schedule', [])
    if schedule_entries:
        lines.append('')
        lines.append('## Work Schedule')
        lines.append('')
        for entry in schedule_entries:
            freq = entry.get('frequency', 'daily').upper()
            time_utc = entry.get('time_utc', '08:00')
            title = entry.get('title', 'Scheduled activity')
            ctx = entry.get('trigger_context', '')
            lines.append(f'### {title} ({freq} at {time_utc} UTC)')
            if ctx:
                lines.append(ctx)
            lines.append('')

    return '\n'.join(lines)


def _generate_default_kpis(role: str, mission: str) -> list:
    """Return a list of structured KPI dicts for metrics.json based on role + mission keywords."""
    combined = (role + ' ' + mission).lower()

    if any(k in combined for k in ['ops', 'operation', 'infra', 'devops', 'sre', 'system']):
        return [
            {'id': 'uptime_pct', 'name': 'Uptime %', 'value': None, 'target': 99.9, 'unit': '%', 'direction': 'up', 'history': []},
            {'id': 'incidents_resolved', 'name': 'Incidents Resolved', 'value': None, 'target': 5, 'unit': 'count', 'direction': 'up', 'history': []},
        ]
    elif any(k in combined for k in ['finance', 'cfo', 'financial', 'budget', 'treasury']):
        return [
            {'id': 'runway_months', 'name': 'Runway', 'value': None, 'target': 18, 'unit': 'months', 'direction': 'up', 'history': []},
            {'id': 'burn_rate', 'name': 'Monthly Burn', 'value': None, 'target': 50000, 'unit': 'USD', 'direction': 'down', 'history': []},
        ]
    elif any(k in combined for k in ['growth', 'marketing', 'cmo', 'acquisition', 'funnel', 'revenue', 'geo']):
        return [
            {'id': 'weekly_signups', 'name': 'Weekly Signups', 'value': None, 'target': 100, 'unit': 'users', 'direction': 'up', 'history': []},
            {'id': 'conversion_rate', 'name': 'Conversion Rate', 'value': None, 'target': 3.5, 'unit': '%', 'direction': 'up', 'history': []},
        ]
    elif any(k in combined for k in ['security', 'shield', 'ciso', 'compliance', 'audit', 'risk']):
        return [
            {'id': 'backup_success_rate', 'name': 'Backup Success Rate', 'value': None, 'target': 100, 'unit': '%', 'direction': 'up', 'history': []},
            {'id': 'open_vulnerabilities', 'name': 'Open Vulnerabilities', 'value': None, 'target': 0, 'unit': 'count', 'direction': 'down', 'history': []},
        ]
    elif any(k in combined for k in ['product', 'cpo', 'feature', 'roadmap', 'ux', 'design']):
        return [
            {'id': 'feature_velocity', 'name': 'Features Shipped', 'value': None, 'target': 4, 'unit': 'per month', 'direction': 'up', 'history': []},
            {'id': 'bug_backlog', 'name': 'Bug Backlog', 'value': None, 'target': 10, 'unit': 'count', 'direction': 'down', 'history': []},
        ]
    elif any(k in combined for k in ['coach', 'hr', 'people', 'talent', 'culture', 'wellbeing']):
        return [
            {'id': 'team_nps', 'name': 'Team NPS', 'value': None, 'target': 50, 'unit': 'points', 'direction': 'up', 'history': []},
            {'id': 'open_issues', 'name': 'Open HR Issues', 'value': None, 'target': 0, 'unit': 'count', 'direction': 'down', 'history': []},
        ]
    else:
        return [
            {'id': 'tasks_completed', 'name': 'Tasks Completed', 'value': None, 'target': 10, 'unit': 'per week', 'direction': 'up', 'history': []},
            {'id': 'quality_score', 'name': 'Quality Score', 'value': None, 'target': 90, 'unit': '%', 'direction': 'up', 'history': []},
        ]


def _generate_default_schedules(de_name: str, de_json: dict) -> dict:
    """Generate role-appropriate default schedules for a new DE."""
    role = (de_json.get('role') or '').lower()
    mission = (de_json.get('mission') or '').lower()
    combined = role + ' ' + mission

    schedules = []
    now = now_iso()

    def _sched(name, frequency, time_utc, days, prompt):
        return {
            'id': f'sched-{_uuid.uuid4().hex[:8]}',
            'name': name,
            'active': True,
            'frequency': frequency,
            'time_utc': time_utc,
            'days': days,
            'prompt': prompt,
            'next_run': _compute_next_run_from_schedule({
                'frequency': frequency, 'time_utc': time_utc, 'days': days
            }),
            'last_run': None,
            'last_session_id': None,
            'created_at': now,
        }

    WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri']
    ALL_DAYS  = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    # ── Universal: Daily Briefing for every DE ──────────────────────────
    schedules.append(_sched(
        'Daily Briefing',
        'daily', '08:00', ALL_DAYS,
        'Start of day: review your KPIs, check your inbox for messages from colleagues, '
        'identify the top 1-3 priorities for today, and report your plan. '
        'If any KPI is off-track, flag it and propose a corrective action.',
    ))

    # ── Role-specific extras ─────────────────────────────────────────────
    ops_kw    = any(k in combined for k in ['ops', 'operation', 'infra', 'devops', 'sre', 'system'])
    finance_kw= any(k in combined for k in ['finance', 'cfo', 'financial', 'budget', 'treasury', 'max'])
    growth_kw = any(k in combined for k in ['growth', 'marketing', 'cmo', 'acquisition', 'funnel', 'revenue'])
    coach_kw  = any(k in combined for k in ['coach', 'hr', 'people', 'talent', 'culture', 'wellbeing'])
    security_kw=any(k in combined for k in ['security', 'shield', 'ciso', 'compliance', 'audit', 'risk'])
    product_kw= any(k in combined for k in ['product', 'cpo', 'feature', 'roadmap', 'ux', 'design'])
    scribe_kw = any(k in combined for k in ['scribe', 'doc', 'knowledge', 'wiki', 'memo', 'communication'])

    if ops_kw:
        schedules.append(_sched(
            'Health Check',
            'daily', '06:00', ALL_DAYS,
            'Run a full infrastructure health check: check all services, disk usage, memory, '
            'and any failed systemd units. Restart anything that is down. '
            'Report what was checked, what was fixed, and overall system status.',
        ))

    if finance_kw:
        schedules.append(_sched(
            'Weekly Financial Review',
            'weekly', '09:00', ['mon'],
            'Weekly financial review: summarise key financial metrics, burn rate, runway, '
            'and any budget variances from last week. Flag anything that needs a human decision.',
        ))

    if growth_kw:
        schedules.append(_sched(
            'Weekly KPI Review',
            'weekly', '09:00', ['mon'],
            'Review all growth KPIs from the past week: traffic, conversions, CAC, LTV. '
            'Compare against targets, identify the biggest gap, and propose one specific action to close it.',
        ))

    if coach_kw:
        schedules.append(_sched(
            'Team Pulse Check',
            'weekly', '09:00', ['fri'],
            'End-of-week people check: review open HR matters, team feedback, and any '
            'wellbeing signals. Summarise what needs follow-up next week.',
        ))

    if security_kw:
        schedules.append(_sched(
            'Daily Security Audit',
            'daily', '07:00', ALL_DAYS,
            'Daily security audit: check auth logs for anomalies, review any new CVEs relevant '
            'to the stack, verify backups completed. Flag any issues immediately.',
        ))

    if product_kw:
        schedules.append(_sched(
            'Weekly Roadmap Review',
            'weekly', '09:00', ['mon'],
            'Review product roadmap progress: what shipped last week, what is at risk, '
            'and what needs a decision from the team. Identify any blockers.',
        ))

    if scribe_kw:
        schedules.append(_sched(
            'Documentation Review',
            'weekly', '14:00', ['fri'],
            'Review documentation health: identify outdated pages, missing docs for recent changes, '
            'and any knowledge gaps flagged by the team. Propose updates.',
        ))

    # No role matched — add a generic weekly review as second schedule
    if len(schedules) == 1:
        schedules.append(_sched(
            'Weekly Review',
            'weekly', '09:00', ['mon'],
            'Weekly self-review: assess progress on your goals and KPIs from the past week. '
            'What was accomplished? What is behind? What one action would have the most impact next week?',
        ))

    return {'schedules': schedules, 'activities': [], 'updated_at': now}


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

        # metrics.json — initialize with role-based KPIs
        role = body.get('role', '')
        mission = body.get('mission', '')
        existing_kpis = body.get('kpis', [])
        default_kpis = [] if existing_kpis else _generate_default_kpis(role, mission)
        (de_dir / 'metrics.json').write_text(json.dumps({
            'updated': None,
            'kpis': default_kpis,
        }, indent=2))

        # memory.md — empty
        (de_dir / 'memory.md').write_text(f'# {de_json["display_name"]} — Memory\n\nCreated {now_iso()}. No entries yet.\n')

        # schedule.json — auto-generated based on role/mission
        initial_schedule = _generate_default_schedules(name, de_json)
        (de_dir / 'schedule.json').write_text(json.dumps(initial_schedule, indent=2))

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

    # GET /de/<name>/metrics  — KPI metrics
    if len(parts) == 3 and parts[2] == 'metrics':
        return handle_de_metrics_get(handler, de_name)

    # GET /de/<name>/schedule  — scheduled activities
    if len(parts) == 3 and parts[2] == 'schedule':
        return handle_de_schedule_get(handler, de_name)

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


def handle_tools_get(handler):
    """GET /tools — return tool list discovered from OpenClaw (or defaults)."""
    result = _get_tools()
    return handler.send_json(200, result)


def handle_tools_rediscover(handler):
    """POST /tools/rediscover — force-refresh tool list from OpenClaw."""
    result = _get_tools(force_rediscover=True)
    return handler.send_json(200, {**result, 'refreshed': True})


def handle_tools_register(handler, body: dict):
    """POST /api/tools/register — register a new custom tool from a JSON definition.

    Required body fields: id, name, description, script
    Optional: icon, script_args, args_schema
    Creates /var/de-framework-tools/{id}.json.
    Returns 409 if already exists, 400 if required fields missing.
    """
    # Validate required fields
    required_fields = ('id', 'name', 'description', 'script')
    missing = [f for f in required_fields if not (body.get(f) or '').strip()]
    if missing:
        return handler.send_json(400, {
            'ok': False,
            'error': f'Missing required fields: {', '.join(missing)}',
        })

    tool_id = body['id'].strip()
    # Validate id format: alphanumeric + underscores + hyphens
    import re as _re
    if not _re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{0,62}$', tool_id):
        return handler.send_json(400, {
            'ok': False,
            'error': 'id must start with a letter and contain only alphanumeric, underscore, or hyphen chars',
        })

    CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CUSTOM_TOOLS_DIR / f'{tool_id}.json'

    if out_path.exists():
        return handler.send_json(409, {
            'ok': False,
            'error': f'Custom tool "{tool_id}" already exists — delete {out_path} to re-register',
        })

    required_creds = body.get('required_credentials', [])
    if not isinstance(required_creds, list):
        required_creds = []

    tool = {
        'id':                   tool_id,
        'name':                 (body.get('name') or tool_id).strip(),
        'description':          body['description'].strip(),
        'icon':                 (body.get('icon') or '🔧').strip(),
        'script':               body['script'].strip(),
        'script_args':          body.get('script_args', []),
        'args_schema':          body.get('args_schema', {}),
        'required_credentials': required_creds,
    }
    out_path.write_text(json.dumps(tool, indent=2, ensure_ascii=False))

    # Immediately register into the running server's TOOL_LIBRARY
    try:
        from backend.core.tool_implementations import make_custom_tool_fn, TOOL_LIBRARY
        schema = tool['args_schema'] or {}
        if not schema.get('type'):
            schema = {'type': 'object', 'properties': {}}
        TOOL_LIBRARY[tool_id] = {
            'name':                 tool_id,
            'description':          tool['description'],
            'input_schema':         schema,
            'fn':                   make_custom_tool_fn(tool['script'], tool['script_args'], required_creds),
            'source':               'custom',
            'required_credentials': required_creds,
        }
    except Exception as e:
        print(f'[handle_tools_register] Live-register failed (tool saved but not hot-loaded): {e}')

    return handler.send_json(201, {'ok': True, 'tool': {**tool, 'source': 'custom'}})


def handle_de_tools_patch(handler, de_name: str, body: dict):
    """PATCH /de/<name>/tools — update tools array in de.json."""
    de_dir = AGENTS_BASE / de_name
    de_json_file = de_dir / 'de.json'
    if not de_json_file.exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})
    try:
        de_data = json.loads(de_json_file.read_text())
        tools = list(body.get('tools', []))
        # Filter to valid tool ids only
        valid_ids = {t['id'] for t in _get_tools().get('tools', [])}
        tools = [t for t in tools if t in valid_ids]
        # Always include required tools regardless of what was sent
        for req_id in REQUIRED_TOOL_IDS:
            if req_id not in tools:
                tools.append(req_id)
        de_data['tools'] = tools
        de_data['updated_at'] = now_iso()
        de_json_file.write_text(json.dumps(de_data, indent=2))
        return handler.send_json(200, {'ok': True, 'tools': tools, 'de': de_name})
    except Exception as e:
        return handler.send_json(500, {'ok': False, 'error': str(e)})


def handle_session_reset(handler, de_name: str, session_id: str):
    """POST /de/<name>/sessions/<id>/reset — mark stale running session as error."""
    session_file = AGENTS_BASE / de_name / 'sessions' / f'{session_id}.json'
    if not session_file.exists():
        return handler.send_json(404, {'error': 'Session not found'})
    try:
        d = json.loads(session_file.read_text())
        if d.get('status') != 'running':
            return handler.send_json(400, {'error': f'Session is not running (status: {d.get("status")})'} )
        d['status'] = 'error'
        d['updated_at'] = now_iso()
        d['completed_at'] = now_iso()
        d.setdefault('steps', []).append({
            'type': 'error',
            'content': 'Session reset manually (was stale/stuck)',
            'ts': now_iso(),
        })
        d['summary'] = 'Session was stuck with no progress and was reset manually.'
        session_file.write_text(json.dumps(d, indent=2))
        return handler.send_json(200, {'ok': True, 'session_id': session_id})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})


def handle_de_metrics_get(handler, de_name: str):
    """GET /de/<name>/metrics — return metrics.json."""
    de_dir = AGENTS_BASE / de_name
    if not (de_dir / 'de.json').exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})
    metrics_file = de_dir / 'metrics.json'
    if not metrics_file.exists():
        return handler.send_json(200, {'kpis': []})
    try:
        data = json.loads(metrics_file.read_text())
        if 'kpis' not in data:
            data['kpis'] = []
        return handler.send_json(200, data)
    except Exception:
        return handler.send_json(200, {'kpis': []})


# ────────────────────────────────────────────────────────────────────────────
# REST /api/des  — programmatic DE management (for agent-to-agent handoff)
# ────────────────────────────────────────────────────────────────────────────

import re as _re
_NAME_RE = _re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,62}$')

_DE_DEFAULTS = {
    'display_name': None,          # falls back to name.upper()
    'color': '#FF4500',
    'autonomy': 1,
    'autonomy_level': 1,
    'tools': [
        'exec_shell', 'read_file', 'write_file',
        'send_telegram', 'web_search',
        'schedule_next_session',
        'ask_colleague', 'report_to_colleague',
        'request_human_decision',
    ],
    'kpis': [],
    'goals': [],
    'responsibilities': {'l0': [], 'l1': [], 'l2': []},
    'hard_constraints': [],
    'data_sources': [],
    'autoresearch': {'enabled': False, 'queries': []},
    'self_evaluation': {'schedule': 'manual'},
}


def _build_de_json_from_api(body: dict) -> dict:
    """Build a de.json dict from POST /api/des body, applying defaults."""
    name = body['name'].strip().lower()
    display_name = body.get('display_name') or name.upper()
    autonomy = body.get('autonomy', body.get('autonomy_level', 1))

    # KPIs: accept list of dicts (API format) or list of strings (legacy)
    raw_kpis = body.get('kpis', [])
    kpi_strings = []
    for k in raw_kpis:
        if isinstance(k, dict):
            target = k.get('target', '')
            unit = k.get('unit', '')
            direction = k.get('direction', '')
            target_str = f"{target} {unit}" if unit else str(target)
            dir_str = f" ({direction})" if direction else ''
            kpi_strings.append(f"{k.get('name', k.get('id', 'KPI'))}: {target_str}{dir_str}")
        else:
            kpi_strings.append(str(k))

    # responsibilities: accept l0/l1/l2 (API) or level_0/level_1/level_2 (legacy)
    raw_resp = body.get('responsibilities', {})
    responsibilities = {
        'level_0': raw_resp.get('level_0') or raw_resp.get('l0') or [],
        'level_1': raw_resp.get('level_1') or raw_resp.get('l1') or [],
        'level_2': raw_resp.get('level_2') or raw_resp.get('l2') or [],
    }

    # triggers — always include user trigger; add cron if schedule defined
    schedule_val = (body.get('self_evaluation') or {}).get('schedule', 'manual')
    triggers = [{'type': 'user', 'description': 'On-demand via portal or API'}]
    if schedule_val and schedule_val != 'manual':
        schedule_labels = {
            'hourly': 'Every hour',
            '3x_daily': '3x daily (08:00, 14:00, 20:00 UTC)',
            'daily': 'Daily at 08:00 UTC',
            'weekly': 'Weekly on Monday at 08:00 UTC',
        }
        triggers.append({
            'type': 'cron',
            'schedule': schedule_labels.get(schedule_val, schedule_val),
            'description': 'Scheduled autonomous run',
        })

    return {
        'name': name,
        'display_name': display_name,
        'role': body.get('role', ''),
        'color': body.get('color', '#FF4500'),
        'autonomy_level': autonomy,
        'mission': body.get('mission', ''),
        'kpis': kpi_strings,
        'responsibilities': responsibilities,
        'hard_constraints': body.get('hard_constraints', []),
        'data_sources': body.get('data_sources', []),
        'autoresearch': body.get('autoresearch', {'enabled': False, 'queries': []}),
        'self_evaluation': body.get('self_evaluation', {'schedule': 'manual'}),
        'tools': body.get('tools', _DE_DEFAULTS['tools']),
        'goals': body.get('goals', []),
        'triggers': triggers,
        'created_at': now_iso(),
        'updated_at': now_iso(),
    }


def handle_api_des_post(handler, body: dict):
    """POST /api/des — create a new Digital Employee programmatically.

    Minimal body: {"name": "aria", "role": "Head of Product", "mission": "..."}
    Full body: see SETUP.md → Creating DEs via API.
    Returns 201 on success, 409 if DE exists, 400 if name invalid.
    """
    name = (body.get('name') or '').strip().lower()
    if not name:
        return handler.send_json(400, {'error': 'name is required'})
    if not _NAME_RE.match(name):
        return handler.send_json(400, {
            'error': 'name must start with a letter/digit and contain only '
                     'alphanumeric, hyphen, or underscore characters'
        })

    de_dir = AGENTS_BASE / name
    if de_dir.exists():
        return handler.send_json(409, {
            'error': f'DE "{name}" already exists',
            'path': str(de_dir),
        })

    try:
        de_dir.mkdir(parents=True)
        (de_dir / 'sessions').mkdir()

        de_json = _build_de_json_from_api(body)

        # de.json
        (de_dir / 'de.json').write_text(json.dumps(de_json, indent=2))

        # metrics.json — initialize with role-based default KPIs
        raw_kpis = body.get('kpis', [])
        default_kpis = [] if raw_kpis else _generate_default_kpis(
            body.get('role', ''), body.get('mission', '')
        )
        (de_dir / 'metrics.json').write_text(json.dumps(
            {'updated': None, 'kpis': default_kpis},
            indent=2
        ))

        # memory.md — empty
        (de_dir / 'memory.md').write_text(
            f'# {de_json["display_name"]} — Memory\n\n'
            f'Created {now_iso()}. No entries yet.\n'
        )

        # decisions.json — empty queue
        (de_dir / 'decisions.json').write_text(
            json.dumps({'pending': [], 'resolved': []}, indent=2)
        )

        # schedule.json — auto-generated based on role/mission
        initial_schedule = _generate_default_schedules(name, de_json)
        (de_dir / 'schedule.json').write_text(json.dumps(initial_schedule, indent=2))

        # job.md — generated from body (reuse existing generator)
        job_md = _generate_job_md({
            **body,
            'display_name': de_json['display_name'],
            'kpis': de_json['kpis'],
            'responsibilities': {
                'level_0': de_json['responsibilities']['level_0'],
                'level_1': de_json['responsibilities']['level_1'],
                'level_2': de_json['responsibilities']['level_2'],
            },
        })
        (de_dir / 'job.md').write_text(job_md)

        return handler.send_json(201, {
            'ok': True,
            'de': de_json,
            'path': str(de_dir),
        })

    except Exception as exc:
        import shutil
        try:
            shutil.rmtree(de_dir)
        except Exception:
            pass
        return handler.send_json(500, {'ok': False, 'error': str(exc)})


def handle_api_des_list(handler):
    """GET /api/des — list all Digital Employees (REST variant of /de-list)."""
    de_names = _get_de_names()
    des = []
    for de_name in de_names:
        de_json_file = AGENTS_BASE / de_name / 'de.json'
        if not de_json_file.exists():
            continue
        try:
            d = json.loads(de_json_file.read_text())
            last_sessions = _de_sessions_list(de_name, limit=1)
            last_session = last_sessions[0] if last_sessions else None
            des.append({
                'name': d.get('name'),
                'display_name': d.get('display_name'),
                'role': d.get('role'),
                'color': d.get('color'),
                'mission': (d.get('mission') or '')[:200],
                'autonomy_level': d.get('autonomy_level', 1),
                'tools': d.get('tools', []),
                'session_count': _de_session_count(de_name),
                'pending_decisions': _de_pending_count(de_name),
                'last_session': last_session,
                'created_at': d.get('created_at'),
                'updated_at': d.get('updated_at'),
            })
        except Exception as exc:
            des.append({'name': de_name, 'error': str(exc)})
    return handler.send_json(200, {'des': des, 'count': len(des), 'ts': now_iso()})


def handle_api_des_get(handler, de_name: str):
    """GET /api/des/{name} — full DE detail (REST variant of /de/<name>)."""
    de_dir = AGENTS_BASE / de_name
    de_json_file = de_dir / 'de.json'
    if not de_json_file.exists():
        return handler.send_json(404, {'error': f'DE not found: {de_name}'})
    try:
        de_data = json.loads(de_json_file.read_text())
        sessions = _de_sessions_list(de_name, limit=20)
        metrics_file = de_dir / 'metrics.json'
        metrics = {}
        if metrics_file.exists():
            try:
                metrics = json.loads(metrics_file.read_text())
            except Exception:
                pass
        return handler.send_json(200, {
            **de_data,
            'session_count': _de_session_count(de_name),
            'pending_decisions': _de_pending_count(de_name),
            'sessions': sessions,
            'metrics': metrics,
            'path': str(de_dir),
        })
    except Exception as exc:
        return handler.send_json(500, {'error': str(exc)})
