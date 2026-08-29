"""
Signup Routes — /signup, /collab, /leads
Handles inbound lead and collaboration enquiry forms.
"""

import json
import os
import urllib.request as _ureq
from backend.config import AGENTS_BASE, PORTAL_INBOX, TELEGRAM_BOT_TOKEN, TELEGRAM_NOTIFY_CHAT_ID, now_iso
from backend.routes.tasks_routes import load_tasks, save_tasks


def _tg_send(text, parse_mode=None):
    """Send a Telegram notification. Silently fails if token/chat not configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_NOTIFY_CHAT_ID:
        return
    try:
        payload = {'chat_id': TELEGRAM_NOTIFY_CHAT_ID, 'text': text}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        tg_body = json.dumps(payload).encode()
        req = _ureq.Request(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            data=tg_body,
            headers={'Content-Type': 'application/json'},
        )
        _ureq.urlopen(req, timeout=5)
    except Exception:
        pass


def handle_signup(handler, body):
    """POST /signup — Agentic Living signup form (public)."""
    import datetime as _dt

    ts = now_iso()
    lead_id = f"lead-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
    country = handler.headers.get('CF-IPCountry', '')

    lead = {
        'id': lead_id, 'ts': ts,
        'name': body.get('name', ''), 'phone': body.get('phone', ''), 'email': body.get('email', ''),
        'source': body.get('source', 'signup-form'), 'page_url': body.get('page_url', ''),
        'referrer': body.get('referrer', ''),
        'utm_source': body.get('utm_source', ''), 'utm_medium': body.get('utm_medium', ''),
        'utm_campaign': body.get('utm_campaign', ''), 'utm_content': body.get('utm_content', ''),
        'utm_term': body.get('utm_term', ''),
        'user_agent': body.get('user_agent', handler.headers.get('User-Agent', '')),
        'language': body.get('language', ''), 'screen': body.get('screen', ''),
        'timezone': body.get('timezone', ''), 'country': country,
        'time_on_page_s': body.get('time_on_page_s'),
        'scroll_depth_pct': body.get('scroll_depth_pct'),
        'sections_viewed': body.get('sections_viewed', []),
        'status': 'new',
    }

    # Persist lead
    leads_file = AGENTS_BASE.parent / 'leads.jsonl'
    with open(leads_file, 'a') as f:
        f.write(json.dumps(lead) + '\n')

    # Create task
    import datetime as _dt2
    task_id = f"task-signup-{_dt2.datetime.now(_dt2.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    utm_line = (
        f"\nSource: {lead['utm_source']}"
        + (f" / {lead['utm_campaign']}" if lead['utm_campaign'] else '')
    ) if lead['utm_source'] else (f"\nReferrer: {lead['referrer']}" if lead['referrer'] else '')

    task = {
        'id': task_id, 'type': 'signup',
        'title': f"Signup: {lead['name'] or lead['phone'] or 'Unknown'}",
        'description': (
            f"New signup on {lead['source']}\n\n"
            f"Name: {lead['name'] or '—'}\n"
            f"Phone: {lead['phone'] or '—'}"
            + (f"\nEmail: {lead['email']}" if lead['email'] else '')
            + utm_line
            + (f"\nLocation: {country}" if country else '')
            + (f"\nTime on page: {lead['time_on_page_s']}s" if lead['time_on_page_s'] else '')
        ),
        'context': lead, 'status': 'open', 'project': lead['source'],
        'dueDate': (_dt2.datetime.now(_dt2.timezone.utc) + _dt2.timedelta(days=1)).strftime('%Y-%m-%d'),
        'createdAt': ts, 'updatedAt': ts, 'source': 'signup-form', 'agent': 'growth',
    }
    tasks = load_tasks()
    tasks.setdefault('open', []).append(task)
    save_tasks(tasks)

    # Telegram notification
    utm_msg = (
        f"\n📊 {lead['utm_source']}"
        + (f" / {lead['utm_campaign']}" if lead['utm_campaign'] else '')
        + (f" / {lead['utm_content']}" if lead['utm_content'] else '')
    ) if lead['utm_source'] else ''
    ref_msg = f"\n🔗 From: {lead['referrer']}" if not lead['utm_source'] and lead['referrer'] else ''
    loc_msg = f"\n📍 {country}" if country else ''
    eng_msg = (
        f"\n⏱ {lead['time_on_page_s']}s on page"
        + (f", {lead['scroll_depth_pct']}% scrolled" if lead['scroll_depth_pct'] else '')
    ) if lead['time_on_page_s'] else ''
    msg = (
        f"🎯 New Signup!\n\n"
        f"👤 {lead['name'] or '—'}\n"
        f"📱 {lead['phone'] or '—'}"
        + (f"\n📧 {lead['email']}" if lead['email'] else '')
        + loc_msg + utm_msg + ref_msg + eng_msg
    )
    _tg_send(msg)

    return handler.send_json(200, {'ok': True, 'id': lead_id})


def handle_collab(handler, body):
    """POST /collab — collaboration enquiry form (public)."""
    import datetime as _dt
    ts = now_iso()
    collab_id = f"collab-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
    name = body.get('name', '—')
    message = body.get('message', '—')
    collab_type = body.get('type', 'General')

    entry = {'id': collab_id, 'ts': ts, 'name': name, 'message': message, 'type': collab_type, 'status': 'new'}

    # Log to JSONL
    collab_file = AGENTS_BASE.parent / 'collabs.jsonl'
    with open(collab_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')

    # Portal task
    task_id = f"task-collab-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    type_emoji = '🎓' if 'Programme' in collab_type else ('🏢' if 'Leadership' in collab_type else '🚀')
    task = {
        'id': task_id, 'type': 'collab-enquiry',
        'title': f"{type_emoji} Collaboration enquiry: {name}",
        'description': f"New enquiry\n\nType: {collab_type}\nName: {name}\n\nMessage:\n{message}",
        'context': entry, 'status': 'open',
        'dueDate': (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=2)).strftime('%Y-%m-%d'),
        'createdAt': ts, 'updatedAt': ts, 'source': 'contact-form', 'agent': 'growth',
    }
    tasks = load_tasks()
    tasks.setdefault('open', []).append(task)
    save_tasks(tasks)

    msg = f"{type_emoji} *New Collaboration Enquiry*\n\n*Type:* {collab_type}\n*Name:* {name}\n\n*Message:*\n{message}"
    _tg_send(msg, parse_mode='Markdown')

    return handler.send_json(200, {'ok': True, 'id': collab_id})


def handle_leads(handler, body):
    """POST /leads — universal form lead submission (public).
    Fully flexible: accepts any fields, writes to tasks.json.
    """
    import datetime as _dt

    lead_source = body.get('source', 'unknown')
    lead_name = body.get('name', '')
    lead_title = body.get('title') or f'Lead: {lead_name or lead_source}'
    lead_contact = body.get('phone') or body.get('whatsapp') or body.get('email') or lead_name

    # Store ALL fields as context
    skip_keys = {'source', 'title'}
    context_fields = {k: v for k, v in body.items() if k not in skip_keys and v}

    task_id = f'task-lead-{_dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")}-{os.urandom(3).hex()}'
    task = {
        'id': task_id,
        'type': 'lead',
        'source': lead_source,
        'title': lead_title,
        'action_text': f'Review and respond to {lead_contact}.' if lead_contact else 'Review this lead.',
        'context': json.dumps(context_fields, ensure_ascii=False)[:4000],
        'estimated_impact': 'New inbound lead',
        'created_at': now_iso(),
        'status': 'open',
    }
    tasks = load_tasks()
    tasks['open'].append(task)
    save_tasks(tasks)

    # Portal inbox entry
    inbox_entry = {
        'ts': now_iso(), 'agent': lead_source,
        'level': 0, 'type': 'lead',
        'summary': f'New lead: {lead_title}',
        'title': lead_title,
    }
    if PORTAL_INBOX:
        with open(PORTAL_INBOX, 'a') as _pf:
            _pf.write(json.dumps(inbox_entry) + '\n')

    # Telegram
    lines = [f'🎯 *New Lead — {lead_source}*\n\n*{lead_title}*']
    display_order = ['name', 'phone', 'whatsapp', 'email']
    shown = set()
    for key in display_order:
        if key in context_fields and context_fields[key]:
            lines.append(f'*{key}:* {context_fields[key]}')
            shown.add(key)
    for key, val in context_fields.items():
        if key not in shown and key not in {'name', 'title'} and val:
            lines.append(f'*{key}:* {str(val)[:300]}')
    _tg_send('\n'.join(lines), parse_mode='Markdown')

    # Write response directly (this endpoint sets its own CORS headers)
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
    handler.end_headers()
    handler.wfile.write(json.dumps({'ok': True, 'id': task_id}).encode())


def handle_signup_list(handler):
    """GET /signup-list (auth required) — return all signup leads."""
    leads_file = AGENTS_BASE.parent / 'leads.jsonl'
    leads = []
    if leads_file.exists():
        for line in leads_file.read_text().splitlines():
            try:
                leads.append(json.loads(line))
            except Exception:
                pass
    return handler.send_json(200, {'total': len(leads), 'leads': list(reversed(leads))})
