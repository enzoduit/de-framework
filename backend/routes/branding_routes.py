"""Branding routes — GET /api/branding · POST /api/branding

Stores white-label config (logo, company name, accent color) in
/var/de-framework-branding.json.  Auth required for both endpoints.
"""

import json
from pathlib import Path

BRANDING_FILE = Path('/var/de-framework-branding.json')

DEFAULTS: dict = {
    'logo_url': '',
    'company_name': 'Digital Employees',
    'accent_color': '#FF4500',
    'favicon_url': '',
}


def _load() -> dict:
    if BRANDING_FILE.exists():
        try:
            data = json.loads(BRANDING_FILE.read_text())
            return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
        except Exception:
            pass
    return dict(DEFAULTS)


def _save(data: dict) -> None:
    BRANDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRANDING_FILE.write_text(json.dumps(data, indent=2))


def handle_branding_get(handler) -> None:
    """GET /api/branding — returns current branding config."""
    handler.send_json(200, _load())


def handle_branding_post(handler, body: dict) -> None:
    """POST /api/branding — update branding config fields."""
    current = _load()
    allowed = set(DEFAULTS.keys())
    for k in allowed:
        if k in body:
            current[k] = str(body[k])
    _save(current)
    handler.send_json(200, {'ok': True, **current})
