"""
Digital Employees Framework — Central Configuration
All secrets and paths loaded from environment variables. No hardcoded credentials.
Copy .env.example to .env and fill in values, then: source .env
"""

import os
import datetime
from pathlib import Path


# ── Server ─────────────────────────────────────────────────────────────────
PORT = int(os.environ.get('PORT') or os.environ.get('DE_API_PORT', 8766))

# ── Auth ────────────────────────────────────────────────────────────────────
AUTH_TOKEN = os.environ.get('DE_API_TOKEN', '')

# ── Anthropic ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# ── Model ───────────────────────────────────────────────────────────────────
# Model used by the ReAct engine for all DE sessions.
# Each DE can override this in de.json via the "model" field.
DE_MODEL = os.environ.get('DE_MODEL', 'claude-haiku-4-5')

# ── Paths ───────────────────────────────────────────────────────────────────
AGENTS_BASE = Path(os.environ.get('AGENTS_DIR', './agents'))
PORTAL_INBOX = AGENTS_BASE / 'portal-inbox.jsonl'
TASKS_FILE = AGENTS_BASE / 'tasks.json'

# ── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_NOTIFY_CHAT_ID = os.environ.get('TELEGRAM_NOTIFY_CHAT_ID', '')

# ── Decisions API ────────────────────────────────────────────────────────────
# URL of the decisions ingest endpoint for human-in-loop notifications.
# Leave blank to skip HTTP notification — decisions are always written to disk.
DECISIONS_API_URL = os.environ.get('DECISIONS_API_URL', '')

# ── ElevenLabs voice agent ───────────────────────────────────────────────────
ELEVENLABS_AGENT_ID = os.environ.get('ELEVENLABS_AGENT_ID', '')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')

# ── Digital Employee names (comma-separated, or auto-discover if empty) ───────
_de_names_env = os.environ.get('DE_NAMES', '')
DE_NAMES = [n.strip() for n in _de_names_env.split(',') if n.strip()] if _de_names_env else None
# If DE_NAMES is None, de_routes will discover DEs dynamically by scanning AGENTS_DIR

# ── Agent display metadata (used by /agents-data endpoint) ───────────────────
# Optional: pre-define display metadata for known agents.
# If an agent has a de.json, its color/role from there takes precedence.
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
