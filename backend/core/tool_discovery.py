"""
Tool Discovery — queries OpenClaw Gateway to get available tools for this installation.

Flow:
  1. GET /api/tools → get_tools() → check tools_cache.json
  2. If no cache → discover_from_openclaw() → parse JSON from LLM response
  3. Cache result in {AGENTS_DIR}/tools_cache.json
  4. Fallback to DEFAULT_TOOL_LIBRARY if OpenClaw unreachable or not configured

Why query OpenClaw:
  The DE Framework is designed for OpenClaw setups. Each OpenClaw installation
  has a different set of tools enabled (policy-filtered per agent). Querying the
  gateway at setup time means the tool list in the portal always reflects what's
  actually available in this specific installation — not a hardcoded assumption.
"""

import json
import os
import re
import pathlib
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', '')
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', '')
AGENTS_DIR = pathlib.Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))

# ── Prompt sent to OpenClaw to discover available tools ──────────────────────

DISCOVERY_PROMPT = """DE_FRAMEWORK_TOOL_DISCOVERY

Output ONLY a JSON array of tools available in this OpenClaw installation that are suitable for autonomous Digital Employees.

Required format (no markdown, no prose, only the array):
[{"id": "exec_shell", "name": "exec_shell", "description": "Run shell commands on the server", "icon": "🖥"}]

Map your available capabilities to these standard DE tool IDs where possible:
- exec_shell → if you can run shell/exec commands
- read_file → if you can read files
- write_file → if you can write/create files
- send_telegram → if you can send Telegram messages
- web_search → if you can search the web
- schedule_next_session → if you can schedule future sessions
- ask_colleague → if you can send messages to other agents
- report_to_colleague → if you can report results to other agents
- request_human_decision → if you can escalate decisions to a human

Only include tools that are actually available and enabled. Output ONLY the JSON array."""

# ── Default fallback (used when OpenClaw is unreachable) ─────────────────────

DEFAULT_TOOL_LIBRARY = [
    {"id": "exec_shell",             "name": "exec_shell",             "description": "Run shell commands on the server",                       "icon": "🖥"},
    {"id": "read_file",              "name": "read_file",              "description": "Read any file on the server",                            "icon": "📄"},
    {"id": "write_file",             "name": "write_file",             "description": "Write or create files on the server",                    "icon": "✏"},
    {"id": "send_telegram",          "name": "send_telegram",          "description": "Send Telegram messages to the owner",                    "icon": "✉"},
    {"id": "web_search",             "name": "web_search",             "description": "Search the web via DuckDuckGo",                         "icon": "🔍"},
    {"id": "schedule_next_session",  "name": "schedule_next_session",  "description": "Plan a follow-up session for yourself",                  "icon": "📅"},
    {"id": "ask_colleague",          "name": "ask_colleague",          "description": "Ask another Digital Employee for help",                  "icon": "💬"},
    {"id": "report_to_colleague",    "name": "report_to_colleague",    "description": "Send a result/update to another Digital Employee",       "icon": "📢"},
    {"id": "request_human_decision", "name": "request_human_decision", "description": "Escalate a decision to the human owner",                 "icon": "🙋"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_path() -> pathlib.Path:
    return AGENTS_DIR / 'tools_cache.json'


def discover_from_openclaw() -> tuple[list, str]:
    """
    Query OpenClaw Gateway to get available tools.
    Returns (tools_list, source) where source is 'openclaw' or 'default'.
    """
    if not OPENCLAW_GATEWAY_URL or not OPENCLAW_GATEWAY_TOKEN:
        print('[tool_discovery] No OpenClaw gateway configured — using defaults')
        return DEFAULT_TOOL_LIBRARY, 'default'

    try:
        payload = json.dumps({
            'model': 'openclaw',
            'messages': [{'role': 'user', 'content': DISCOVERY_PROMPT}],
            'max_tokens': 1024,
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
        resp = urlopen(req, timeout=30)
        data = json.loads(resp.read())
        content = data['choices'][0]['message']['content'].strip()

        # Extract JSON array from response (handles markdown code fences too)
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        if match:
            tools = json.loads(match.group())
            if isinstance(tools, list) and tools:
                # Validate each entry has required fields
                valid = [
                    t for t in tools
                    if isinstance(t, dict) and t.get('id') and t.get('name')
                ]
                if valid:
                    print(f'[tool_discovery] Discovered {len(valid)} tools from OpenClaw')
                    return valid, 'openclaw'

        print(f'[tool_discovery] Could not parse tool list from OpenClaw response — using defaults')
        return DEFAULT_TOOL_LIBRARY, 'default'

    except (URLError, Exception) as e:
        print(f'[tool_discovery] OpenClaw query failed: {e} — using defaults')
        return DEFAULT_TOOL_LIBRARY, 'default'


def get_tools(force_rediscover: bool = False) -> dict:
    """
    Get the tool library. Returns dict with keys: tools, source, discovered_at.

    Args:
        force_rediscover: If True, bypass cache and query OpenClaw fresh.
    """
    cache = _cache_path()

    if not force_rediscover and cache.exists():
        try:
            cached = json.loads(cache.read_text())
            if isinstance(cached.get('tools'), list) and cached['tools']:
                return cached
        except Exception:
            pass

    # Discover (or fallback)
    tools, source = discover_from_openclaw()
    result = {
        'tools': tools,
        'source': source,
        'discovered_at': _now_iso(),
        'openclaw_url': OPENCLAW_GATEWAY_URL or None,
    }

    # Write cache
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f'[tool_discovery] Could not write cache: {e}')

    return result
