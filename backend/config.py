"""
Digital Employees Framework — Central Configuration
All secrets and paths loaded from environment variables. No hardcoded credentials.
Copy .env.example to .env and fill in values, then: source .env
"""

import os
import datetime
from pathlib import Path


# ── Server ─────────────────────────────────────────────────────────────────
PORT = int(os.environ.get('DE_API_PORT', 8766))

# ── Auth ────────────────────────────────────────────────────────────────────
AUTH_TOKEN = os.environ.get('DE_API_TOKEN', '')

# ── Paths ───────────────────────────────────────────────────────────────────
AGENTS_BASE = Path(os.environ.get('AGENTS_DIR', '/opt/de-framework/agents'))
PORTAL_INBOX = AGENTS_BASE / 'portal-inbox.jsonl'
TASKS_FILE = AGENTS_BASE / 'tasks.json'

# ── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_NOTIFY_CHAT_ID = os.environ.get('TELEGRAM_NOTIFY_CHAT_ID', '')

# ── ElevenLabs voice agent ───────────────────────────────────────────────────
ELEVENLABS_AGENT_ID = os.environ.get('ELEVENLABS_AGENT_ID', '')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')

# ── Digital Employee names (comma-separated, or auto-discover if empty) ───────
_de_names_env = os.environ.get('DE_NAMES', '')
DE_NAMES = [n.strip() for n in _de_names_env.split(',') if n.strip()] if _de_names_env else None
# If DE_NAMES is None, de_routes will discover DEs dynamically by scanning AGENTS_DIR

# ── Agent display metadata (used by /agents-data endpoint) ───────────────────
AGENT_META = {
    'max':           {'role': 'CFO · Cost Intelligence',                     'color': '#22c55e'},
    'aria':          {'role': 'Head of Product · Agent School',               'color': '#0d7c66'},
    'geo':           {'role': 'Growth Lead · GEO Visibility',                 'color': '#1a56db'},
    'ops':           {'role': 'Operations Manager · Uptime',                  'color': '#6366F1'},
    'coach':         {'role': 'Personal Sports Coach · Garmin',               'color': '#10B981'},
    'scribe':        {'role': 'Head of Documentation · Memory',               'color': '#F59E0B'},
    'flow':          {'role': 'Chief of Agentic Efficiency',                  'color': '#FF4500'},
    'shield':        {'role': 'Data Security Officer · Compliance',           'color': '#EF4444'},
    'growth':        {'role': 'Chief Growth Hacker · Partner Discovery',      'color': '#FF6B35'},
}


# ── Utilities ───────────────────────────────────────────────────────────────

def now_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
