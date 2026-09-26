"""
Decisions Routes — /decisions, /decide, /audit-log, /revert
"""

import json
import datetime
import subprocess as _sp
from pathlib import Path
from backend.config import AGENTS_BASE, now_iso


# ── User Input Persistence ────────────────────────────────────────────────────

def _save_user_input(de_name: str, input_type: str, data: dict) -> None:
    """Save user input to AGENTS_BASE/<de>/user_inputs/YYYY-MM-DD-HH-MM-<type>.json.
    Never raises — failures are silently swallowed.
    """
    try:
        safe_de = de_name if de_name and de_name != 'system' else 'system'
        ui_dir = AGENTS_BASE / safe_de / 'user_inputs'
        ui_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-%H-%M')
        fname = f'{ts}-{input_type}.json'
        (ui_dir / fname).write_text(json.dumps(data, indent=2))
    except Exception:
        pass

_SESSION_RUNNER = Path(__file__).parent.parent / 'core' / 'session_runner.py'
from backend.routes.tasks_routes import create_human_task, execute_decision


# ── GET handlers ──────────────────────────────────────────────────────────────

def handle_decisions_get(handler):
    """GET /decisions — return all pending decisions across all agents."""
    all_pending = []

    # Root-level decisions.json (system agents write here)
    root_file = AGENTS_BASE / 'decisions.json'
    if root_file.exists():
        try:
            d = json.loads(root_file.read_text())
            items = d if isinstance(d, list) else d.get('pending', [])
            for item in items:
                if item.get('status', 'pending') == 'pending':
                    item['_agent_dir'] = item.get('agent', 'system')
                    all_pending.append(item)
        except Exception:
            pass

    # Per-agent decisions.json files (subdirectories only)
    for agent_dir in AGENTS_BASE.iterdir():
        if not agent_dir.is_dir():
            continue
        decisions_file = agent_dir / 'decisions.json'
        if decisions_file.exists():
            try:
                d = json.loads(decisions_file.read_text())
                for item in d.get('pending', []):
                    item['_agent_dir'] = agent_dir.name
                    all_pending.append(item)
            except Exception:
                pass

    return handler.send_json(200, {'pending': all_pending, 'count': len(all_pending)})


def handle_audit_log_get(handler):
    """GET /audit-log — return last 100 audit log entries."""
    audit_file = AGENTS_BASE / 'audit-log.jsonl'
    try:
        limit = 100
        entries = []
        if audit_file.exists():
            lines = [l for l in audit_file.read_text().splitlines() if l.strip()]
            for line in reversed(lines[-limit:]):
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return handler.send_json(200, {'entries': entries, 'count': len(entries)})
    except Exception as e:
        return handler.send_json(500, {'error': str(e)})


# ── POST handlers ─────────────────────────────────────────────────────────────

def handle_decide(handler, body):
    """POST /decide — approve, reject, or send back a decision."""
    decision_id = body.get('id')
    action = body.get('action')  # 'approve', 'reject', or 'sendback'
    note = body.get('note', '')

    if not decision_id or action not in ('approve', 'reject', 'sendback'):
        return handler.send_json(400, {'error': 'missing id or invalid action (approve/reject/sendback)'})

    # Search order: root-level decisions.json first, then per-agent subdirs
    candidate_files = []
    root_file = AGENTS_BASE / 'decisions.json'
    if root_file.exists():
        candidate_files.append(('system', root_file))
    for agent_dir in AGENTS_BASE.iterdir():
        if not agent_dir.is_dir():
            continue
        df = agent_dir / 'decisions.json'
        if df.exists():
            candidate_files.append((agent_dir.name, df))

    for _agent_name, decisions_file in candidate_files:
        agent_dir = decisions_file.parent
        if not decisions_file.exists():
            continue
        try:
            decisions = json.loads(decisions_file.read_text())
            pending = decisions.get('pending', [])
            match = next((item for item in pending if item['id'] == decision_id), None)
            if match:
                # ── P1: Persist user input BEFORE processing ───────────────────────────────
                _de_for_save = agent_dir.name if agent_dir != AGENTS_BASE else 'system'
                _choice_map = {'approve': 'approved', 'reject': 'rejected', 'sendback': 'deferred'}
                _save_user_input(_de_for_save, 'decision', {
                    'timestamp': now_iso(),
                    'type': 'decision',
                    'session_id': match.get('session_id', ''),
                    'de': _de_for_save,
                    'decision_id': decision_id,
                    'raw_input': note,
                    'choice': _choice_map.get(action, action),
                    'context': {'question': match.get('title', match.get('description', ''))},
                })
                # ── End P1 ────────────────────────────────────────────────────────

                # SEND BACK: keep in pending, add feedback, queue for re-thinking
                if action == 'sendback':
                    match['status'] = 'replied'
                    match['ed_feedback'] = note
                    match['replied_at'] = now_iso()
                    match['sendback_count'] = match.get('sendback_count', 0) + 1
                    # Move from pending to resolved so it leaves "Needs Attention"
                    decisions['pending'] = [i for i in pending if i['id'] != decision_id]
                    resolved_key = 'resolved' if 'resolved' in decisions else 'resolved'
                    if resolved_key not in decisions:
                        decisions[resolved_key] = []
                    decisions[resolved_key].append(match)
                    decisions_file.write_text(json.dumps(decisions, indent=2))

                    # Resume the paused session — inject Ed's reply as context, re-run runner
                    sess_id = match.get('session_id')
                    de_from_dec = match.get('agent', '')
                    session_resumed = None
                    if sess_id and de_from_dec:
                        sess_file = AGENTS_BASE / de_from_dec / 'sessions' / f'{sess_id}.json'
                        if sess_file.exists():
                            sess_data = json.loads(sess_file.read_text())
                            if sess_data.get('status') == 'paused_human':
                                reply_ctx = f'[Human reply to "{match.get("title","")}"] {note}'
                                sess_data['trigger_context'] = reply_ctx
                                steps = sess_data.get('steps', [])
                                steps.append({'type': 'human_reply', 'ts': now_iso(), 'content': reply_ctx})
                                sess_data['steps'] = steps
                                sess_data['status'] = 'pending'
                                sess_file.write_text(json.dumps(sess_data, indent=2))
                                _rlog = f'/tmp/sendback-{de_from_dec}-{sess_id}.log'
                                _sp.Popen(
                                    ['python3', str(_SESSION_RUNNER), de_from_dec, sess_id],
                                    stdout=open(_rlog, 'w'), stderr=_sp.STDOUT,
                                    cwd=str(AGENTS_BASE),
                                )
                                session_resumed = sess_id

                    return handler.send_json(200, {
                        'status': 'ok',
                        'action': 'sentback',
                        'id': decision_id,
                        'session_resumed': session_resumed,
                        'message': 'Reply sent — session is continuing.' if session_resumed else 'Reply recorded.',
                    })

                # APPROVE or REJECT: move to resolved
                match['status'] = action + 'd'  # approved / rejected
                match['resolved_at'] = now_iso()
                match['resolution_note'] = note
                decisions['pending'] = [item for item in pending if item['id'] != decision_id]
                resolved_key = (
                    'resolved' if 'resolved' in decisions
                    else 'history' if 'history' in decisions
                    else 'resolved'
                )
                if resolved_key not in decisions:
                    decisions[resolved_key] = []
                decisions[resolved_key].append(match)
                decisions_file.write_text(json.dumps(decisions, indent=2))

                result = {'status': 'ok', 'action': action + 'd', 'id': decision_id}

                # On reject with reason — write to DE inbox so next session sees it
                if action == 'reject' and note:
                    inbox_file = agent_dir / 'workspace' / 'inbox.jsonl'
                    inbox_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(inbox_file, 'a') as f:
                        f.write(json.dumps({
                            'type': 'decision_rejected',
                            'ts': now_iso(),
                            'decision_id': decision_id,
                            'title': match.get('title', ''),
                            'reason': note,
                            'message': f"Your decision '{match.get('title','')}' was rejected. Reason: {note}. Rethink your approach.",
                        }) + '\n')

                if action == 'approve':
                    # If decision came from a paused session, resume it
                    sess_id = match.get('session_id')
                    de_from_dec = match.get('agent', '')
                    if sess_id and de_from_dec:
                        sess_file = AGENTS_BASE / de_from_dec / 'sessions' / f'{sess_id}.json'
                        if sess_file.exists():
                            sess_data = json.loads(sess_file.read_text())
                            if sess_data.get('status') == 'paused_human':
                                resume_payload = json.dumps({
                                    'approved': True,
                                    'note': note,
                                    'decision_id': decision_id,
                                })
                                _rlog = f'/tmp/resume-{de_from_dec}-{sess_id}.log'
                                _sp.Popen(
                                    ['python3', str(_SESSION_RUNNER), de_from_dec, sess_id],
                                    stdout=open(_rlog, 'w'),
                                    stderr=_sp.STDOUT,
                                    cwd=str(AGENTS_BASE),
                                )
                                result['session_resumed'] = sess_id

                    if match.get('execution_type') == 'human':
                        task = create_human_task(match)
                        result['task_created'] = task['id']
                        result['task_type'] = 'human'
                    else:
                        executed = execute_decision(match, agent_dir)
                        result['executed'] = executed

                return handler.send_json(200, result)
        except Exception as e:
            return handler.send_json(500, {'error': str(e)})

    return handler.send_json(404, {'error': 'decision not found'})


def handle_audit_log_post(handler, body):
    """POST /audit-log — append an entry to the audit log."""
    audit_file = AGENTS_BASE / 'audit-log.jsonl'
    if not body.get('agent') or not body.get('action'):
        return handler.send_json(400, {'error': 'missing agent or action'})
    body['ts'] = body.get('ts', now_iso())
    with open(audit_file, 'a') as f:
        f.write(json.dumps(body) + '\n')
    return handler.send_json(200, {'ok': True})


def handle_revert(handler, body):
    """POST /revert — queue a revert for an audit log entry."""
    entry_id = body.get('id')
    audit_file = AGENTS_BASE / 'audit-log.jsonl'

    # Find the audit entry
    target = None
    if audit_file.exists():
        for line in audit_file.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get('id') == entry_id:
                    target = e
            except Exception:
                pass

    if not target:
        return handler.send_json(404, {'error': 'audit entry not found'})
    if not target.get('revertible') or not target.get('revert_prompt'):
        return handler.send_json(400, {'error': 'not revertible'})

    queue_file = AGENTS_BASE / 'decision-execute-queue.jsonl'
    revert_decision = {
        'id': f'revert-{entry_id}',
        'agent': target.get('agent', 'unknown'),
        'title': f'REVERT: {target.get("action", "")}',
        'description': f'Reverting autonomous action from {target.get("ts", "")}',
        'proposed_action': target['revert_prompt'],
        'reasoning_context': target['revert_prompt'],
        'resolution_note': 'Triggered by portal revert button',
        'execution_type': 'self',
    }
    with open(queue_file, 'a') as f:
        f.write(json.dumps({
            'ts': now_iso(),
            'decision': revert_decision,
            'agent_dir': target.get('agent', 'ops'),
            'note': 'Portal revert',
        }) + '\n')

    # Mark as reverted in audit log
    with open(audit_file, 'a') as f:
        f.write(json.dumps({
            'ts': now_iso(),
            'agent': 'system',
            'level': 0,
            'action': f'Revert queued for: {entry_id}',
            'detail': 'Revert triggered via portal',
            'revertible': False,
        }) + '\n')

    return handler.send_json(200, {'ok': True, 'queued': f'revert-{entry_id}'})


# ── P2: Decision Thread ────────────────────────────────────────────────────

def handle_decision_thread(handler, decision_id: str):
    """GET /decisions/<id>/thread — decision + session context timeline."""
    found = None
    found_de = None

    # Search root-level decisions.json
    root_file = AGENTS_BASE / 'decisions.json'
    if root_file.exists():
        try:
            d = json.loads(root_file.read_text())
            all_items = d.get('pending', []) + d.get('resolved', []) + d.get('history', [])
            for item in all_items:
                if item.get('id') == decision_id:
                    found = item
                    found_de = 'system'
                    break
        except Exception:
            pass

    # Search per-agent decisions.json files
    if not found:
        for agent_dir in AGENTS_BASE.iterdir():
            if not agent_dir.is_dir():
                continue
            df = agent_dir / 'decisions.json'
            if not df.exists():
                continue
            try:
                d = json.loads(df.read_text())
                all_items = d.get('pending', []) + d.get('resolved', []) + d.get('history', [])
                for item in all_items:
                    if item.get('id') == decision_id:
                        found = item
                        found_de = agent_dir.name
                        break
            except Exception:
                pass
            if found:
                break

    if not found:
        return handler.send_json(404, {'error': 'decision not found'})

    # Load session file
    sess_id = found.get('session_id')
    session_data = None
    if sess_id and found_de and found_de != 'system':
        sess_file = AGENTS_BASE / found_de / 'sessions' / f'{sess_id}.json'
        if sess_file.exists():
            try:
                session_data = json.loads(sess_file.read_text())
            except Exception:
                pass

    steps = (session_data or {}).get('steps', [])

    # Count steps before the matching decision_request, and after resolution
    steps_before = 0
    steps_after = 0
    found_dec_step = False
    found_res_step = False
    for step in steps:
        stype = step.get('type', '')
        if not found_dec_step:
            if stype == 'decision_request' and step.get('decision_id') == decision_id:
                found_dec_step = True
            else:
                steps_before += 1
        elif not found_res_step:
            if stype in ('decision_response', 'human_reply'):
                found_res_step = True
        else:
            steps_after += 1

    # Build timeline
    timeline = []
    if steps_before > 0:
        timeline.append({'type': 'agent_working', 'steps': steps_before,
                         'label': f'Agent analyzed options ({steps_before} steps)'})
    timeline.append({'type': 'human_pause', 'label': '⏸ Waiting for human decision'})

    dec_status = found.get('status', 'pending')
    label_map = {
        'approved': '✅ Human approved',
        'rejected': '🛑 Human rejected',
        'replied': '↩️ Human replied',
    }
    if dec_status in label_map:
        answer_text = found.get('resolution_note') or found.get('ed_feedback', '')
        ts_resolved = found.get('resolved_at') or found.get('replied_at', '')
        timeline.append({
            'type': 'human_decided',
            'label': label_map[dec_status],
            'answer': answer_text,
            'timestamp': ts_resolved,
        })
        if steps_after > 0:
            timeline.append({'type': 'agent_resumed', 'steps': steps_after,
                             'label': f'Agent executed plan ({steps_after} steps)'})

    session_status = (session_data or {}).get('status', 'unknown')
    session_before = ({'id': sess_id, 'status': 'paused_human', 'steps_before_pause': steps_before}
                      if sess_id else None)
    session_after = ({'id': sess_id, 'status': session_status, 'steps_after_resume': steps_after}
                     if sess_id else None)

    human_answer = None
    if dec_status in label_map:
        human_answer = {
            'choice': dec_status,
            'note': found.get('resolution_note') or found.get('ed_feedback', ''),
            'timestamp': found.get('resolved_at') or found.get('replied_at', ''),
        }

    return handler.send_json(200, {
        'decision': found,
        'session_before': session_before,
        'session_after': session_after,
        'human_answer': human_answer,
        'timeline': timeline,
    })


# ── Feedback (P1 complement) ──────────────────────────────────────────────────

def handle_feedback_post(handler, body: dict):
    """POST /feedback — save portal feedback to user_inputs."""
    de_name = body.get('de', 'system')
    _save_user_input(de_name, 'feedback', {
        'timestamp': now_iso(),
        'type': 'feedback',
        'de': de_name,
        'session_id': body.get('session_id', ''),
        'message': body.get('message', ''),
        'rating': body.get('rating'),
    })
    return handler.send_json(200, {'ok': True})
