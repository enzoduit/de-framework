# Pattern: Transversal Agent

A Transversal Agent serves multiple departments or project areas. It has no fixed primary supervisor — instead, any authorized colleague can send it a task via a shared inbox, and it processes one task at a time.

---

## How Transversal Differs from Specialist

| | Specialist DE | Transversal DE |
|---|---|---|
| **Supervisor** | One fixed chief or direct client | No fixed chief — "reference chief" only |
| **Schedule** | Own cron schedule | On-demand (inbox-triggered) |
| **Context scope** | Full project context at session start | Only the context for the current task |
| **KPIs** | Operational metric (SoAV, leads) | Throughput + quality (tasks completed, revision rate) |
| **Primary trigger** | `cron` | `user` with task in inbox |
| **Identity** | Belongs to one team | Belongs to no team; available to all |

---

## When to Use This Pattern

Use a transversal agent when:

- A skill is needed by **2+ independent DEs** (e.g. copywriting, translation, data extraction)
- The work is **task-bounded** (clear input → clear output, no long-running state)
- A dedicated specialist for each team would be wasteful (low volume per team)
- The role in the client's org chart is explicitly cross-functional ("shared service")

Do NOT make an agent transversal if:
- It owns a metric or KPI that belongs to one business unit
- It needs to maintain deep context about one project over time
- It is on a tight cron schedule with time-sensitive duties

---

## Context Isolation: The Most Important Rule

A transversal agent gets **only the context for the current task**. Not the full project strategy. Not all experiments. Just:

1. What is the task? (from the brief/inbox)
2. What is the target audience or objective? (attached to the task)
3. What is the desired output format?

**Why:** Transversal agents are hired guns. Giving them full strategy context wastes tokens, adds confusion, and risks cross-contamination between clients.

**How to implement context isolation in job.md:**

```markdown
## STEP 0 — Read your task only. Ignore everything else.

1. Read `/var/de-agents/<name>/inbox.jsonl` → get the latest unprocessed task
2. The task message contains: `task`, `context` (1–2 sentences), `output_format`, `deadline`
3. Execute ONLY that task, using ONLY the provided context
4. Do NOT read other DEs' workspace files
5. Do NOT use memory from previous sessions unless the task explicitly references it
```

---

## Priority Handling: Who Gets Served First?

When multiple colleagues request the transversal agent in the same period, use this order:

1. **Urgency flag** in the inbox message (`"priority": "high"`)
2. **FIFO** (first message received) — use the inbox timestamp
3. **Reference Chief** gets priority over lateral colleagues at equal priority

Each inbox entry must include:

```json
{
  "ts": "2026-09-23T09:00:00Z",
  "from": "grow_client",
  "priority": "normal",
  "task": "Write a 3-sentence Instagram caption for the September campaign",
  "context": "Target: female donors 35-55. Emotional hook: Eufrasia story. CTA: link in bio.",
  "output_format": "Plain text, max 150 chars, no emojis",
  "deadline": "2026-09-24T17:00:00Z"
}
```

The transversal agent processes one task per session. After completing, it removes the entry from inbox and writes output to the requester's shared workspace or a designated output path.

---

## Reference Chief

Every transversal agent has a **reference chief** — the DE that defines quality standards and reviews output when disputes arise. The reference chief does NOT micromanage daily tasks.

Declare in `job.md`:

```markdown
**Reference Chief:** `<project>_chief` — defines quality standards; reviews escalations only.
```

Declare in `de.json`:

```json
"reference_chief": "<project>_chief"
```

---

## KPIs for a Transversal Agent

```yaml
de: "content_agent"
kpis:
  - id: tasks_completed_this_week
    name: "Tasks Completed (This Week)"
    measure: "python3 workspace/measure_tasks.py --metric completed --period week"
    unit: "tasks"
    direction: "up"
    target: null
    target_auto: true
    target_improvement: 0.10
    frequency: weekly

  - id: revision_rate
    name: "Revision Rate (% tasks requiring redo)"
    measure: "python3 workspace/measure_tasks.py --metric revision_rate"
    unit: "%"
    direction: "lower_is_better"
    target: 15
    frequency: weekly

  - id: inbox_backlog
    name: "Inbox Backlog (pending tasks)"
    measure: "python3 -c \"import json; tasks=[json.loads(l) for l in open('inbox.jsonl') if l.strip()]; print(len([t for t in tasks if not t.get('done')]))\""
    unit: "tasks"
    direction: "lower_is_better"
    target: 5
    frequency: per_session
```

---

## Transversal Agent job.md Template

```markdown
# <NAME> — <Role Title> (Transversal)

**Mission:** Complete cross-team <skill> tasks on demand with high quality and fast turnaround.

**Reference Chief:** `<project>_chief` — quality standards + escalation path.

**KPIs:**
- Tasks completed per week (auto-baseline + 10%)
- Revision rate (target: ≤15%)
- Inbox backlog (target: ≤5 pending)

**Workspace:** `/var/de-agents/<name>/workspace/` — task log and quality notes only.

---

## STEP 0 — Read your task ONLY. Context isolation is non-negotiable.

1. Read `inbox.jsonl` → find first entry where `done != true`, sorted by priority then timestamp
2. If inbox is empty → write one line to workspace/log.md: `[date] No tasks — idle` → stop
3. Extract ONLY: `task`, `context`, `output_format` from the inbox entry
4. Mark the entry as `"in_progress": true` before starting work

---

## SESSION TYPE: `user` — Task Execution (max 8 iterations)

1. Read the task from inbox (Step 0)
2. Execute the task using ONLY the provided context
   - Do not read other projects' strategy files
   - Do not consult memory from other clients
3. Write output to the path specified in the task, or to `workspace/output--<task_id>.md`
4. Notify the requesting DE: append to their `inbox.jsonl`:
   ```json
   {"ts": "...", "from": "<name>", "type": "task_complete", "task_id": "...", "output_path": "..."}
   ```
5. Mark the task as done: update `inbox.jsonl` entry with `"done": true, "completed_at": "..."`
6. Append to `workspace/log.md`: `[date] Task: <task title> → Done (quality: self-rated X/5)`

---

## SESSION TYPE: `cron` — Backlog Review (max 5 iterations)

1. Run pre_fetch.py briefing → check KPIs
2. If backlog > 5 tasks → prioritize and execute the highest-priority one
3. If all KPIs on track → log one line → done

---

## Authority levels

**Level 0 — do immediately:**
- Read inbox tasks
- Execute any task that matches your skill
- Write output files
- Notify requesting DE of completion

**Level 1 — do it, log to workspace:**
- Request clarification from requesting DE (write to their inbox)
- Extend deadline by 1 day (write note to requesting DE)

**Level 2 — create decision, stop, wait:**
- Task requires access you don't have
- Task conflicts with another client's confidentiality
- Quality concern: output would be misleading or harmful
- Anything not explicitly in Level 0/1

**Never:**
- Use one client's context for another client's task
- Exceed 8 iterations for a single task
- Process more than 1 task per session
- Read full project strategy files from any DE's workspace
```

---

## Inviting the Transversal Agent (from a Specialist DE)

When a specialist DE needs a transversal agent's help, it writes to the transversal's inbox:

```bash
# In the specialist DE's job.md — Level 1 action:
# Write to content_agent inbox when copy is needed
python3 -c "
import json, time
task = {
    'ts': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
    'from': '<my_de_name>',
    'priority': 'normal',
    'task': 'Write subject line for September email campaign',
    'context': 'Audience: existing donors. Goal: reactivate lapsed supporters. Tone: warm.',
    'output_format': 'Two options, max 60 chars each',
    'deadline': '2026-09-25T17:00:00Z'
}
with open('/var/de-agents/content_agent/inbox.jsonl', 'a') as f:
    f.write(json.dumps(task) + '\n')
print('Task queued for content_agent')
"
```

---

## Directory Setup

```bash
# Standard DE directories
mkdir -p /var/de-agents/<name>/{workspace,logs,sessions}

# Transversals don't have a shared/ dir — they use their inbox.jsonl
touch /var/de-agents/<name>/inbox.jsonl
```

No `shared/` directory needed — the transversal agent's output goes directly to the requesting DE's path or a specified output file.
