"""
Tasks Routes — /tasks, /task-done
Also contains task helpers used by decisions_routes.
"""

import json
from backend.config import AGENTS_BASE, TASKS_FILE, PORTAL_INBOX, now_iso


# ── Task helpers ─────────────────────────────────────────────────────────────

def load_tasks():
    """Load tasks.json, returning {'open': [], 'done': []} on failure."""
    if TASKS_FILE.exists():
        try:
            return json.loads(TASKS_FILE.read_text())
        except Exception:
            pass
    return {'open': [], 'done': []}


def save_tasks(tasks):
    """Write tasks dict to tasks.json."""
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


def create_human_task(decision):
    """Create a human-action task from an approved decision. Returns the task dict."""
    tasks = load_tasks()
    task = {
        'id': 'task-' + decision['id'],
        'decision_id': decision['id'],
        'agent': decision.get('agent', '?'),
        'title': decision.get('title', ''),
        'action_text': decision.get('proposed_action', ''),
        'context': decision.get('reasoning_context', ''),
        'estimated_impact': decision.get('estimated_impact', ''),
        'created_at': now_iso(),
        'approved_at': decision.get('resolved_at', now_iso()),
        'status': 'open',
    }
    tasks['open'].append(task)
    save_tasks(tasks)
    return task


def execute_decision(decision, agent_dir):
    """Write approved decision to queue — decision-executor cron picks it up within 2 min."""
    queue_file = AGENTS_BASE / 'decision-execute-queue.jsonl'
    entry = {
        'ts': now_iso(),
        'decision': decision,
        'agent_dir': agent_dir.name,
        'note': decision.get('resolution_note', ''),
    }
    with open(queue_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    return f"Queued for execution (agent: {decision.get('agent', '?')}, id: {decision.get('id', '?')[:20]})"


# ── Route handlers ────────────────────────────────────────────────────────────

def handle_tasks_get(handler):
    """GET /tasks — return open and done tasks."""
    tasks = load_tasks()
    return handler.send_json(200, {
        'open': tasks.get('open', []),
        'done': tasks.get('done', []),
        'open_count': len(tasks.get('open', [])),
        'done_count': len(tasks.get('done', [])),
    })


def handle_task_done(handler, body):
    """POST /task-done — mark a task done and notify originating agent."""
    task_id = body.get('id')
    if not task_id:
        return handler.send_json(400, {'error': 'missing id'})

    tasks = load_tasks()
    match = next((t for t in tasks['open'] if t['id'] == task_id), None)
    if not match:
        return handler.send_json(404, {'error': 'task not found'})

    match['status'] = 'done'
    match['done_at'] = now_iso()
    tasks['open'] = [t for t in tasks['open'] if t['id'] != task_id]
    tasks.setdefault('done', []).append(match)
    save_tasks(tasks)

    # Notify the originating agent via cron queue
    agent_name = match.get('agent', '')
    notify_prompt = (
        f"Ed has completed the task you requested: \"{match.get('title', '')}\". "
        f"Task ID: {task_id}. Decision ID: {match.get('decision_id', '')}. "
        f"You can now continue any follow-up work that depended on this action. "
        f"Update your memory.md and experiments.jsonl with the outcome if relevant."
    )
    queue_file = AGENTS_BASE / 'decision-execute-queue.jsonl'
    queue_entry = {
        'ts': now_iso(),
        'decision': {
            'id': task_id + '-done',
            'agent': agent_name,
            'title': f'Task done: {match.get("title", "")}',
            'reasoning_context': notify_prompt,
            'execution_type': 'self',
        },
        'agent_dir': agent_name,
        'note': 'task-done notification',
    }
    with open(queue_file, 'a') as f:
        f.write(json.dumps(queue_entry) + '\n')

    return handler.send_json(200, {'ok': True, 'task_id': task_id, 'agent_notified': agent_name})
