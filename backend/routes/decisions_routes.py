"""
Decisions Routes — /decisions, /decide, /audit-log, /revert
"""

import json
import subprocess as _sp
from backend.config import AGENTS_BASE, now_iso
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
                # SEND BACK: keep in pending, add feedback, queue for re-thinking
                if action == 'sendback':
                    match['status'] = 'pending'
                    match['ed_feedback'] = note
                    match['sendback_at'] = now_iso()
                    match['sendback_count'] = match.get('sendback_count', 0) + 1
                    decisions_file.write_text(json.dumps(decisions, indent=2))

                    feedback_prompt = f"""## DECISION SENT BACK FOR REVISION

**Decision ID:** {match['id']}
**Agent:** {match.get('agent', '?').upper()}
**Original title:** {match.get('title', '')}

**What was proposed:**
{match.get('proposed_action', '')}

**Ed's feedback / new direction:**
{note}

**Your task:** Rethink this decision based on Ed's feedback. Update the decision in {AGENTS_BASE}/{agent_dir.name}/decisions.json — find the decision by ID and update:
- proposed_action: revised concrete action based on Ed's feedback
- description: updated reasoning
- estimated_impact: updated if relevant
- reasoning_context: include what changed and why

Keep status as 'pending'. Do NOT create a new decision — update the existing one in place.
After updating, confirm what changed in a brief message to Ed."""

                    queue_file = AGENTS_BASE / 'decision-execute-queue.jsonl'
                    entry = {
                        'ts': now_iso(),
                        'decision': match,
                        'agent_dir': agent_dir.name,
                        'note': note,
                        'action': 'sendback',
                        'prompt_override': feedback_prompt,
                    }
                    with open(queue_file, 'a') as f:
                        f.write(json.dumps(entry) + '\n')

                    return handler.send_json(200, {
                        'status': 'ok',
                        'action': 'sentback',
                        'id': decision_id,
                        'queued': True,
                        'message': 'Decision sent back to agent for revision with your feedback.',
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
                                    ['python3', str(AGENTS_BASE / 'session_runner.py'),
                                     de_from_dec, sess_id, '--resume', resume_payload],
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
