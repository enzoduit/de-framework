"""
Credential Store Routes — /api/credentials

AES-256 (Fernet) encrypted credential storage for custom tool scripts.
Key is derived from DE_API_TOKEN via PBKDF2 — no separate key file needed.

Storage layout:
  /var/de-framework-credentials/
    index.json          — metadata only (never stores plaintext values)
    META_API_KEY.enc    — Fernet-encrypted value (one file per credential)
"""

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.config import AUTH_TOKEN

CREDS_DIR = Path(os.environ.get('DE_CREDS_DIR', '/var/de-framework-credentials'))
CREDS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = CREDS_DIR / 'index.json'

_ID_RE = re.compile(r'^[A-Z][A-Z0-9_]{0,127}$')


# ─── Fernet helper ───────────────────────────────────────────────────────────

def _fernet():
    """Return a Fernet instance keyed from DE_API_TOKEN via PBKDF2."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError(
            "cryptography package not installed — run: pip install cryptography"
        )
    token = AUTH_TOKEN or ''
    raw_key = hashlib.pbkdf2_hmac(
        'sha256',
        token.encode(),
        b'de-framework-creds',
        100_000,
        dklen=32,
    )
    key = base64.urlsafe_b64encode(raw_key)
    return Fernet(key)


def encrypt_value(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_credential(cred_id: str) -> str | None:
    """Decrypt a stored credential. Returns None if not found or decryption fails."""
    enc_file = CREDS_DIR / f'{cred_id}.enc'
    if not enc_file.exists():
        return None
    try:
        token = enc_file.read_bytes()
        return _fernet().decrypt(token).decode()
    except Exception:
        return None


# ─── Index helpers ────────────────────────────────────────────────────────────

def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except Exception:
            pass
    return {'credentials': {}}


def _save_index(data: dict) -> None:
    INDEX_FILE.write_text(json.dumps(data, indent=2))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_cred_exists(cred_id: str, exists: bool) -> None:
    """Update index.json after a credential file is created or deleted."""
    index = _load_index()
    if exists:
        if cred_id not in index['credentials']:
            index['credentials'][cred_id] = {
                'id': cred_id,
                'description': '',
                'created_at': _now_iso(),
                'last_used': None,
                'tool_ids': [],
            }
    else:
        index['credentials'].pop(cred_id, None)
    _save_index(index)


def credential_exists(cred_id: str) -> bool:
    return (CREDS_DIR / f'{cred_id}.enc').exists()


def credential_status(cred_id: str) -> str:
    """Return 'set' or 'missing'."""
    return 'set' if credential_exists(cred_id) else 'missing'


def update_last_used(cred_id: str) -> None:
    """Record the last_used timestamp in index.json for a credential."""
    index = _load_index()
    if cred_id in index['credentials']:
        index['credentials'][cred_id]['last_used'] = _now_iso()
        _save_index(index)


# ─── Route handlers ───────────────────────────────────────────────────────────

def handle_credentials_post(handler, body: dict):
    """POST /api/credentials — store (create/overwrite) a credential."""
    cred_id = (body.get('id') or '').strip().upper()
    value = body.get('value', '')
    description = (body.get('description') or '').strip()

    if not cred_id:
        return handler.send_json(400, {'ok': False, 'error': 'id is required'})
    if not _ID_RE.match(cred_id):
        return handler.send_json(400, {
            'ok': False,
            'error': 'id must be UPPER_SNAKE_CASE (letters, digits, underscores, starting with a letter)',
        })
    if not value:
        return handler.send_json(400, {'ok': False, 'error': 'value is required'})

    try:
        enc = encrypt_value(value)
    except RuntimeError as e:
        return handler.send_json(500, {'ok': False, 'error': str(e)})

    enc_file = CREDS_DIR / f'{cred_id}.enc'
    enc_file.write_bytes(enc)

    # Update index — preserve existing metadata if overwriting
    index = _load_index()
    existing = index['credentials'].get(cred_id, {})
    index['credentials'][cred_id] = {
        'id': cred_id,
        'description': description or existing.get('description', ''),
        'created_at': existing.get('created_at', _now_iso()),
        'updated_at': _now_iso(),
        'last_used': existing.get('last_used'),
        'tool_ids': existing.get('tool_ids', []),
    }
    _save_index(index)

    return handler.send_json(200, {'ok': True, 'id': cred_id})


def handle_credentials_get(handler):
    """GET /api/credentials — list all credentials (metadata only, never values)."""
    index = _load_index()
    # Filter to only creds that actually have an .enc file (sync in case manual deletion)
    result = []
    for cred_id, meta in sorted(index['credentials'].items()):
        if (CREDS_DIR / f'{cred_id}.enc').exists():
            result.append({
                'id': cred_id,
                'description': meta.get('description', ''),
                'created_at': meta.get('created_at'),
                'updated_at': meta.get('updated_at'),
                'last_used': meta.get('last_used'),
                'tool_ids': meta.get('tool_ids', []),
            })
    return handler.send_json(200, {'credentials': result, 'count': len(result)})


def handle_credentials_delete(handler, cred_id: str):
    """DELETE /api/credentials/{id} — remove a credential."""
    cred_id = cred_id.upper()
    enc_file = CREDS_DIR / f'{cred_id}.enc'
    if not enc_file.exists():
        return handler.send_json(404, {'ok': False, 'error': f'Credential {cred_id} not found'})
    enc_file.unlink()
    _set_cred_exists(cred_id, False)
    return handler.send_json(200, {'ok': True, 'id': cred_id})
