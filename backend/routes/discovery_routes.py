"""
Tool Discovery from Agent — scans workspace scripts, .env files,
and OpenClaw integrations to surface available capabilities as tool candidates.
"""

import json
import os
import re
import pathlib
from urllib.request import urlopen, Request

OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', '')
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', '')
CUSTOM_TOOLS_DIR = pathlib.Path(os.environ.get('CUSTOM_TOOLS_DIR', '/var/de-framework-tools'))
WORKSPACE_ROOT = pathlib.Path(os.environ.get('AGENT_WORKSPACE', '/root/.openclaw/workspace'))


def _icon_for_script(name: str) -> str:
    """Guess an icon based on script name keywords."""
    n = name.lower()
    if any(k in n for k in ['meta', 'facebook', 'fb']): return '📊'
    if any(k in n for k in ['google', 'gmail', 'sheet']): return '📧'
    if any(k in n for k in ['telegram', 'tg', 'bot']): return '✉️'
    if any(k in n for k in ['github', 'git']): return '🐙'
    if any(k in n for k in ['backup', 'sync']): return '💾'
    if any(k in n for k in ['report', 'stats', 'analytics', 'kpi']): return '📈'
    if any(k in n for k in ['monitor', 'check', 'health', 'ping']): return '🔍'
    if any(k in n for k in ['send', 'notify', 'alert', 'notif']): return '🔔'
    if any(k in n for k in ['fetch', 'download', 'scrape', 'crawl']): return '🌐'
    if any(k in n for k in ['deploy', 'build', 'publish']): return '🚀'
    if name.endswith('.py'): return '🐍'
    if name.endswith('.sh'): return '⚙️'
    if name.endswith('.js') or name.endswith('.ts'): return '📜'
    return '🔧'


def _script_to_id(name: str) -> str:
    """Convert script filename to a clean tool id."""
    stem = pathlib.Path(name).stem
    clean = re.sub(r'[^a-z0-9]+', '_', stem.lower()).strip('_')
    return clean[:50]


def _human_name(name: str) -> str:
    """Convert script filename to a human-readable name."""
    stem = pathlib.Path(name).stem
    return stem.replace('_', ' ').replace('-', ' ').title()


def _already_registered(tool_id: str) -> bool:
    """Check if a tool with this id is already in CUSTOM_TOOLS_DIR."""
    if not CUSTOM_TOOLS_DIR.exists():
        return False
    return (CUSTOM_TOOLS_DIR / f'{tool_id}.json').exists()


def discover_workspace_scripts() -> list:
    """
    Scan the agent workspace for executable scripts.
    Returns list of candidate dicts.
    """
    candidates = []
    if not WORKSPACE_ROOT.exists():
        return candidates

    SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env', '.tox'}
    SCRIPT_EXTS = {'.sh', '.py', '.js', '.ts', '.rb', '.php'}
    SKIP_PATTERNS = ['test_', '_test', 'conftest', 'setup.py', '__init__', 'requirements']

    found = []
    for root, dirs, files in os.walk(WORKSPACE_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = pathlib.Path(fname).suffix.lower()
            if ext not in SCRIPT_EXTS:
                continue
            if any(pat in fname.lower() for pat in SKIP_PATTERNS):
                continue
            fpath = pathlib.Path(root) / fname
            found.append(fpath)
        if len(found) > 200:
            break

    for fpath in found[:100]:
        rel = str(fpath.relative_to(WORKSPACE_ROOT))
        tool_id = _script_to_id(fpath.name)
        if not tool_id:
            continue
        ext = fpath.suffix.lower()
        if ext == '.py':
            script = f'python3 {fpath}'
        elif ext == '.sh':
            script = f'bash {fpath}'
        elif ext in ('.js', '.ts'):
            script = f'node {fpath}'
        else:
            script = str(fpath)

        candidates.append({
            'id': tool_id,
            'name': _human_name(fpath.name),
            'description': f'Run {rel}',
            'icon': _icon_for_script(fpath.name),
            'script': script,
            'source_path': str(fpath),
            'source_type': 'workspace_script',
            'already_registered': _already_registered(tool_id),
        })

    return candidates


def discover_env_credentials() -> list:
    """
    Scan common .env files and /etc/ env files for API key names (NOT values).
    Returns list of credential key name candidates.
    """
    cred_names = set()

    ENV_LOCATIONS = [
        WORKSPACE_ROOT / '.env',
        WORKSPACE_ROOT / '.env.local',
        pathlib.Path('/etc/de-framework.env'),
        pathlib.Path('/etc/environment'),
        pathlib.Path('/root/.env'),
        pathlib.Path('/root/.openclaw/workspace/.env'),
    ]

    API_KEY_PATTERN = re.compile(
        r'^([A-Z][A-Z0-9_]{2,}(?:_API_KEY|_TOKEN|_SECRET|_KEY|_ID|_PASS|_PASSWORD|_AUTH|_ACCESS|_ACCOUNT|_CLIENT|_WEBHOOK))=',
        re.MULTILINE
    )

    for env_path in ENV_LOCATIONS:
        if env_path.exists():
            try:
                text = env_path.read_text(errors='replace')
                for m in API_KEY_PATTERN.finditer(text):
                    cred_names.add(m.group(1))
            except Exception:
                pass

    return sorted(cred_names)


def discover_openclaw_integrations() -> list:
    """
    Query OpenClaw gateway for configured integrations/channels.
    Returns list of integration candidates.
    """
    if not OPENCLAW_GATEWAY_URL or not OPENCLAW_GATEWAY_TOKEN:
        return []

    try:
        req = Request(
            f'{OPENCLAW_GATEWAY_URL.rstrip("/")}/tools',
            headers={'Authorization': f'Bearer {OPENCLAW_GATEWAY_TOKEN}'},
        )
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        tools = data if isinstance(data, list) else data.get('tools', [])
        result = []
        for t in tools:
            tool_id = t.get('id') or t.get('name', '')
            if not tool_id:
                continue
            result.append({
                'id': tool_id,
                'name': t.get('name', tool_id),
                'description': t.get('description', f'OpenClaw tool: {tool_id}'),
                'icon': t.get('icon', '⚡'),
                'source_type': 'openclaw_native',
                'already_registered': _already_registered(tool_id),
            })
        return result
    except Exception:
        return []


def handle_discover(handler):
    """POST /api/tools/discover-from-agent — comprehensive tool candidate discovery."""
    scripts = discover_workspace_scripts()
    credentials = discover_env_credentials()
    integrations = discover_openclaw_integrations()

    seen_ids = set()
    all_candidates = []
    for c in scripts + integrations:
        if c['id'] not in seen_ids:
            seen_ids.add(c['id'])
            all_candidates.append(c)

    return handler.send_json(200, {
        'ok': True,
        'candidates': all_candidates,
        'credential_names': credentials,
        'counts': {
            'workspace_scripts': len(scripts),
            'openclaw_integrations': len(integrations),
            'credential_names': len(credentials),
            'total': len(all_candidates),
        }
    })
