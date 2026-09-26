"""
Costs Routes — GET /costs, DELETE /cron/<id>
Estimates API spend per DE based on session step counts.
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from backend.config import AGENTS_BASE, now_iso

# Rough cost estimate: sonnet ≈ $0.003/1K tokens, ~500 tokens/step → $0.0015/step
COST_PER_STEP = 0.0015

_SKIP = frozenset({
    'portal-inbox.jsonl', 'de-trigger.sh', 'feedback.db',
    'tools_cache.json', 'monitor-status.json', 'decision-execute-queue.jsonl',
})


def _parse_dt(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def handle_costs_get(handler):
    """GET /costs — cost overview per DE for the last 30 days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    by_de = []
    total_usd = 0.0

    for de_dir in sorted(AGENTS_BASE.iterdir()):
        if not de_dir.is_dir():
            continue
        if de_dir.name in _SKIP or '.' in de_dir.name:
            continue

        de_name = de_dir.name
        sessions_dir = de_dir / 'sessions'
        if not sessions_dir.exists():
            continue

        sessions_30d = 0
        total_steps = 0

        for sess_file in sessions_dir.iterdir():
            if not sess_file.is_file() or sess_file.suffix != '.json':
                continue
            try:
                sd = json.loads(sess_file.read_text())
            except Exception:
                continue
            # Filter by 30-day window
            created_at = sd.get('created_at', '')
            if created_at:
                dt = _parse_dt(created_at)
                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
            sessions_30d += 1
            for step in sd.get('steps', []):
                if step.get('type') == 'action':
                    total_steps += 1

        if sessions_30d == 0:
            continue

        estimated_usd = round(total_steps * COST_PER_STEP, 4)
        total_usd += estimated_usd
        avg_steps = round(total_steps / sessions_30d, 1)

        # Pull schedule metadata
        schedule_text = None
        cron_id = None
        sched_file = de_dir / 'schedule.json'
        if sched_file.exists():
            try:
                sched_data = json.loads(sched_file.read_text())
                scheds = sched_data.get('schedules', [])
                if scheds:
                    s = scheds[0]
                    freq = s.get('frequency', '')
                    time_utc = s.get('time_utc', '08:00')
                    schedule_text = f"{freq} at {time_utc} UTC"
                    cron_id = s.get('cron_id')  # Set only if openclaw cron registered
            except Exception:
                pass

        by_de.append({
            'de': de_name,
            'sessions_30d': sessions_30d,
            'total_steps': total_steps,
            'estimated_usd': estimated_usd,
            'avg_steps_per_session': avg_steps,
            'cron_id': cron_id,
            'schedule': schedule_text,
        })

    # Biggest spenders first
    by_de.sort(key=lambda x: x['estimated_usd'], reverse=True)

    return handler.send_json(200, {
        'generated_at': now_iso(),
        'total_estimated_usd': round(total_usd, 4),
        'note': 'Estimates based on step counts (action type). Not exact billing.',
        'by_de': by_de,
    })


def handle_cron_delete(handler, cron_id: str):
    """DELETE /cron/<id> — remove an openclaw cron job."""
    try:
        result = subprocess.run(
            ['openclaw', 'cron', 'rm', cron_id],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return handler.send_json(200, {'ok': True, 'cron_id': cron_id})
        err = (result.stderr or result.stdout or 'unknown error').strip()
        return handler.send_json(500, {'error': err, 'cron_id': cron_id})
    except FileNotFoundError:
        return handler.send_json(500, {'error': 'openclaw CLI not found'})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})
