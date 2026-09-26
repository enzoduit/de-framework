"""
Inbox Routes — GET /inbox
Aggregates the most recent session output for every active DE.
Returns a feed sorted by last activity, newest first.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.config import AGENTS_BASE, now_iso

# DEs to always exclude (demo / test stubs)
_EXCLUDE_PREFIXES = ('stale-demo', 'test-stale', 'decision-execute-queue')
_SKIP_DE_NAMES = {'portal-inbox.jsonl', 'de-trigger.sh', 'feedback.db', 'tools_cache.json', 'monitor-status.json'}


def _parse_dt(s: str):
    """Parse ISO timestamp to datetime (UTC-aware). Returns None on failure."""
    if not s:
        return None
    try:
        # Handle both with and without timezone suffix
        s = s.replace('Z', '+00:00')
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _newest_session_file(sessions_dir: Path, de_name: str):
    """Return the newest real session JSON file for a DE, or None."""
    if not sessions_dir.exists():
        return None
    candidates = []
    prefix = f'ws-{de_name}-2026'
    for f in sessions_dir.iterdir():
        if not f.is_file() or not f.suffix == '.json':
            continue
        name = f.stem  # filename without .json
        # Must start with ws-<de>-2026 (not a demo/stale file)
        if not name.startswith(prefix):
            continue
        # Exclude any file whose name contains stale/demo markers
        skip = False
        for excl in _EXCLUDE_PREFIXES:
            if excl in name:
                skip = True
                break
        if skip:
            continue
        candidates.append(f)
    if not candidates:
        return None
    # Sort alphabetically — ws-<de>-YYYYMMDD-HHMMSS-<hex> sorts correctly by date
    candidates.sort(key=lambda f: f.name)
    return candidates[-1]


def _extract_summary(session_data: dict) -> str:
    """Return best available summary text (≤300 chars)."""
    # 1. Top-level summary field
    s = session_data.get('summary', '')
    if s:
        return s[:300]
    # 2. Last 'complete' step with a summary key
    for step in reversed(session_data.get('steps', [])):
        if step.get('type') == 'complete' and step.get('summary'):
            return step['summary'][:300]
    # 3. Last step with any content
    for step in reversed(session_data.get('steps', [])):
        c = step.get('content', '')
        if c:
            return c[:300]
    return ''


def _load_de_meta(de_dir: Path) -> dict:
    """Load de.json for display_name, role, color, and kpis."""
    de_file = de_dir / 'de.json'
    if not de_file.exists():
        return {}
    try:
        return json.loads(de_file.read_text())
    except Exception:
        return {}


def handle_inbox_get(handler):
    """GET /inbox — aggregated recent DE session feed."""
    items = []

    for de_dir in sorted(AGENTS_BASE.iterdir()):
        # Skip non-directories and known non-DE entries
        if not de_dir.is_dir():
            continue
        if de_dir.name in _SKIP_DE_NAMES:
            continue
        # Skip names that look like data files
        if '.' in de_dir.name:
            continue

        de_name = de_dir.name
        sessions_dir = de_dir / 'sessions'
        session_file = _newest_session_file(sessions_dir, de_name)
        if not session_file:
            continue  # No sessions yet — skip

        try:
            session_data = json.loads(session_file.read_text())
        except Exception:
            continue

        meta = _load_de_meta(de_dir)

        # Build display_name from de.json: prefer display_name, fallback role, fallback uppercased name
        display_name = meta.get('display_name') or ''
        role = meta.get('role') or ''
        if display_name and role:
            full_display = f"{display_name} — {role}"
        elif display_name:
            full_display = display_name
        elif role:
            full_display = f"{de_name.upper()} — {role}"
        else:
            full_display = de_name.upper()

        # KPIs — may be string list (e.g. ops) or object list with label/value (e.g. grow_minimist)
        raw_kpis = meta.get('kpis', [])
        kpis = []
        for kpi_raw in raw_kpis[:2]:
            if isinstance(kpi_raw, dict):
                label = kpi_raw.get('label', '')
                target = kpi_raw.get('target')
                value = kpi_raw.get('value')
                unit = kpi_raw.get('unit', '')
                if target is not None and value is not None:
                    label = f"{label}: {value}/{target} {unit}".strip()
                kpis.append({'label': label})
            else:
                kpis.append({'label': str(kpi_raw)})

        created_at = session_data.get('created_at', '')
        status = session_data.get('status', 'unknown')
        steps = session_data.get('steps', [])

        items.append({
            'de': de_name,
            'display_name': full_display,
            'session_id': session_data.get('id', session_file.stem),
            'status': status,
            'steps': len(steps),
            'created_at': created_at,
            'summary': _extract_summary(session_data),
            'kpis': kpis,
            'color': meta.get('color', '#6366f1'),
        })

    # Sort by created_at descending (newest first); missing dates go to the end
    def sort_key(item):
        dt = _parse_dt(item.get('created_at', ''))
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    items.sort(key=sort_key, reverse=True)

    return handler.send_json(200, {
        'generated_at': now_iso(),
        'count': len(items),
        'items': items,
    })
