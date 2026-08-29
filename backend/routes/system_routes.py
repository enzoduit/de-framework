"""
System Routes — /health, /pageviews, /pageview, /agents-data, /system-data, /settings-data, /update-voice-prompt
"""

import json
import subprocess as _sp
import urllib.request as _ureq
from backend.config import AGENTS_BASE, AGENT_META, ELEVENLABS_AGENT_ID, ELEVENLABS_API_KEY, now_iso


def handle_pageviews(handler):
    """GET /pageviews — return aggregated pageview statistics."""
    pv_file = AGENTS_BASE / 'pageviews.jsonl'
    if not pv_file.exists():
        return handler.send_json(200, {
            'total': 0, 'by_domain': {}, 'by_page': {}, 'referrers': {}
        })

    views = []
    for line in pv_file.read_text().splitlines():
        try:
            views.append(json.loads(line))
        except Exception:
            pass

    by_domain = {}
    by_page = {}
    referrers = {}
    for v in views:
        d = v.get('domain', '?')
        p = v.get('path', '/')
        r = v.get('referrer', 'direct')
        by_domain[d] = by_domain.get(d, 0) + 1
        by_page[p] = by_page.get(p, 0) + 1
        if r and r != 'direct':
            try:
                from urllib.parse import urlparse
                host = urlparse(r).netloc or r
                referrers[host] = referrers.get(host, 0) + 1
            except Exception:
                pass

    return handler.send_json(200, {
        'total': len(views),
        'by_domain': dict(sorted(by_domain.items(), key=lambda x: -x[1])),
        'by_page': dict(sorted(by_page.items(), key=lambda x: -x[1])[:20]),
        'referrers': dict(sorted(referrers.items(), key=lambda x: -x[1])[:20]),
        'last_seen': views[-1].get('ts') if views else None,
    })


def handle_pageview(handler, body):
    """POST /pageview — record a pageview event."""
    pv_file = AGENTS_BASE / 'pageviews.jsonl'
    entry = {
        'ts': now_iso(),
        'domain': body.get('domain', '?'),
        'path': body.get('path', '/'),
        'referrer': body.get('referrer', ''),
        'ua': handler.headers.get('User-Agent', '')[:120],
    }
    with open(pv_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    return handler.send_json(200, {'ok': True})


def handle_agents_data(handler):
    """GET /agents-data — return metrics, decisions, and recent activity for all agents."""
    agents_data = {}
    for agent_name, meta in AGENT_META.items():
        agent_dir = AGENTS_BASE / agent_name
        entry = {**meta, 'name': agent_name.upper()}

        # metrics.json
        metrics_file = agent_dir / 'metrics.json'
        if metrics_file.exists():
            try:
                m = json.loads(metrics_file.read_text())
                entry['metrics'] = m.get('kpis', m)
                entry['last_updated'] = m.get('last_updated')
            except Exception:
                entry['metrics'] = {}
        else:
            entry['metrics'] = {}

        # pending decisions count
        decisions_file = agent_dir / 'decisions.json'
        if decisions_file.exists():
            try:
                d = json.loads(decisions_file.read_text())
                entry['pending_decisions'] = len(d.get('pending', []))
            except Exception:
                entry['pending_decisions'] = 0
        else:
            entry['pending_decisions'] = 0

        # last 3 portal-inbox entries for this agent
        inbox = []
        inbox_file = AGENTS_BASE / 'portal-inbox.jsonl'
        if inbox_file.exists():
            try:
                lines = inbox_file.read_text().splitlines()
                for line in reversed(lines):
                    try:
                        item = json.loads(line)
                        if item.get('agent') == agent_name:
                            inbox.append({
                                'ts': item.get('timestamp', item.get('ts', '')),
                                'summary': item.get('summary', '')[:120],
                                'level': item.get('level', 0),
                            })
                            if len(inbox) >= 3:
                                break
                    except Exception:
                        pass
            except Exception:
                pass
        entry['recent_activity'] = inbox

        agents_data[agent_name] = entry

    return handler.send_json(200, {'agents': agents_data, 'ts': now_iso()})


def handle_system_data(handler):
    """GET /system-data — return cron job status summary."""
    try:
        r = _sp.run(
            ['openclaw', 'cron', 'list', '--json'],
            capture_output=True, text=True, timeout=10,
        )
        cron_data = json.loads(r.stdout) if r.returncode == 0 else {'jobs': []}
    except Exception:
        cron_data = {'jobs': []}

    jobs = cron_data.get('jobs', [])
    error_jobs = [j for j in jobs if j.get('state', {}).get('consecutiveErrors', 0) > 0]
    ok_jobs = [j for j in jobs if j.get('state', {}).get('consecutiveErrors', 0) == 0 and j.get('enabled')]
    summary = [{
        'id': j.get('id', ''),
        'name': j.get('name', ''),
        'enabled': j.get('enabled', False),
        'errors': j.get('state', {}).get('consecutiveErrors', 0),
        'lastStatus': j.get('state', {}).get('lastRunStatus', ''),
        'lastError': j.get('state', {}).get('lastError', ''),
        'lastRun': j.get('state', {}).get('lastRunAtMs', 0),
        'nextRun': j.get('state', {}).get('nextRunAtMs', 0),
        'schedule': j.get('schedule', {}),
    } for j in jobs]

    return handler.send_json(200, {
        'ts': now_iso(),
        'total': len(jobs),
        'ok': len(ok_jobs),
        'errors': len(error_jobs),
        'jobs': summary,
    })


def handle_settings_data(handler):
    """GET /settings-data — return masked credentials and gateway status."""
    creds = []
    # Attempt to load deployment config file for display (no secrets in response)
    cf_file = AGENTS_BASE.parent / 'railway' / 'cloudflare-config.json'
    try:
        cf = json.loads(cf_file.read_text())

        def mask(v):
            return ('•' * max(0, len(v) - 4) + v[-4:]) if v else '—'

        creds = [
            {
                'label': 'Cloudflare DNS Token',
                'masked': mask(cf.get('dns_edit_token', ''))[:40],
                'status': 'ok' if cf.get('dns_edit_token') else 'missing',
            },
            {
                'label': 'Cloudflare Account',
                'masked': cf.get('account_name', '?'),
                'status': 'ok',
            },
            {
                'label': 'DE API Token',
                'masked': '•' * 15 + ' (configured)',
                'status': 'ok',
            },
            {
                'label': 'ElevenLabs Agent',
                'masked': (ELEVENLABS_AGENT_ID[:12] + '…') if ELEVENLABS_AGENT_ID else '—',
                'status': 'ok' if ELEVENLABS_AGENT_ID else 'missing',
            },
        ]
    except Exception as e:
        creds = [{'label': 'Config file not found', 'masked': str(e)[:50], 'status': 'error'}]

    # Gateway / OpenClaw status
    try:
        r = _sp.run(['openclaw', 'status', '--json'], capture_output=True, text=True, timeout=5)
        gw_status = 'ok' if r.returncode == 0 else 'error'
    except Exception:
        gw_status = 'unknown'

    return handler.send_json(200, {
        'ts': now_iso(),
        'credentials': creds,
        'gateway_status': gw_status,
    })


def handle_update_voice_prompt(handler, body):
    """POST /update-voice-prompt — update ElevenLabs voice agent prompt."""
    prompt = body.get('prompt', '')
    first_message = body.get('first_message', '')

    if not prompt:
        return handler.send_json(400, {'error': 'no prompt'})
    if not ELEVENLABS_AGENT_ID or not ELEVENLABS_API_KEY:
        return handler.send_json(500, {'error': 'ElevenLabs credentials not configured'})

    agent_update = {'prompt': {'prompt': prompt}}
    if first_message:
        agent_update['first_message'] = first_message

    payload = json.dumps({'conversation_config': {'agent': agent_update}}).encode()
    req = _ureq.Request(
        f'https://api.elevenlabs.io/v1/convai/agents/{ELEVENLABS_AGENT_ID}',
        data=payload,
        headers={'xi-api-key': ELEVENLABS_API_KEY, 'Content-Type': 'application/json'},
        method='PATCH',
    )
    try:
        _ureq.urlopen(req, timeout=10)
        return handler.send_json(200, {'ok': True})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})
