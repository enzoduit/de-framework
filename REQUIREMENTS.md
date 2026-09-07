# Digital Employee Framework — Requirements

> Based on all design discussions and inputs. This is the source of truth for what the framework must deliver.

---

## What is a Digital Employee?

A Digital Employee (DE) is an autonomous AI agent with a defined role, owned metrics, and a clear decision boundary. It reasons, acts with tools, and loops in a human only when genuinely needed. It is not a chatbot. It is a worker with a job description, goals, and accountability.

The framework exists so that:
- Anyone can define a DE (no AI engineering knowledge needed)
- The DE executes work autonomously in a ReAct loop
- A non-technical manager can see exactly what each DE did, whether it worked, and what it needs
- The same framework works for any role — ops, growth, finance, research, whatever

---

## 1. DE Identity (de.json)

Every DE has exactly one `de.json` that defines who it is.

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | Unique slug (lowercase, no spaces) |
| `display_name` | ✅ | Human-readable name shown in portal |
| `role` | ✅ | Job title (e.g. "Operations Manager") |
| `color` | ✅ | Hex color for visual identity in portal |
| `mission` | ✅ | One paragraph: what this DE owns and what success looks like |
| `goals` | ✅ | Array of specific, time-bound goals (e.g. "99.9% uptime by Q4") |
| `kpis` | ✅ | Array of measurable KPIs — must include name + target + unit |
| `autonomy_level` | ✅ | 0 = full auto, 1 = act + notify, 2 = always ask first |
| `responsibilities.level_0` | ✅ | Actions DE executes without asking |
| `responsibilities.level_1` | ✅ | Actions DE executes but logs and notifies about |
| `responsibilities.level_2` | ✅ | Actions DE must ask human before doing |
| `tools` | ✅ | Explicit list of tools this DE is authorized to use |
| `questions_to_ask_yourself` | ✅ | Self-check questions DE runs at end of every session |
| `guardrails` | ✅ | Explicit conditions that trigger human escalation |
| `hard_constraints` | ✅ | Lines the DE never crosses regardless of instructions |
| `colleagues` | — | Other DE names this DE can communicate with |
| `data_sources` | — | URLs, files, or commands DE reads for context |
| `triggers` | — | How sessions are triggered (cron, user, metric threshold) |
| `self_evaluation.schedule` | — | How often DE reviews its own KPI performance |

### Example: goals vs kpis

**KPI** = the measurement: `"Service uptime — target: 99.9%, unit: %"`  
**Goal** = the commitment: `"Achieve 99.9% uptime across all core services by 2026-12-31"`

KPIs track the metric. Goals define the promise.

---

## 2. The ReAct Loop

Every session runs as a Reason → Act → Observe loop.

```
TRIGGER (user / cron / colleague / metric threshold)
  ↓
REASON — claude-sonnet-4-6 reads job.md + context, decides what to do
  ↓
ACT — calls a tool (exec_shell, web_search, send_telegram, etc.)
  ↓
OBSERVE — reads the result
  ↓
REASON — decides next step based on result
  ↓
... repeats until done, stuck, or human input needed ...
  ↓
COMPLETE — writes summary, updates metrics.json, schedules follow-ups
```

The loop is **always visible** in the portal — every reasoning step, every tool call, every observation — so a non-technical manager can see exactly what happened.

---

## 3. Tools

### Standard Tool Set (all DEs get these by default)

| Tool | What it does |
|---|---|
| `exec_shell` | Run a shell command. Returns stdout/stderr. Primary tool for system checks, data queries, scripts. |
| `read_file` | Read a file from DE workspace or global workspace. |
| `write_file` | Write to DE's own workspace directory. |
| `send_telegram` | Send a message to owner's Telegram thread. Use for alerts, results, status reports. |
| `web_search` | Search the web via Perplexity. Returns answer + citations. |
| `schedule_next_session` | Schedule a follow-up work session (once / daily / weekly). The DE plans its own work. |
| `ask_colleague` | Send a question to another DE's inbox. Async — DE continues, colleague responds in their next session. |
| `report_to_colleague` | Reply to a colleague who asked a question. Closes the async loop. |
| `request_human_decision` | Escalate to human. Creates a decision card in portal. Session pauses. |

### Tool Configuration per DE

- `de.json` has an explicit `tools` array listing which tools this DE is authorized to use
- Portal settings shows **full tool list** with toggle per tool per DE
- Future: custom tool endpoints (webhook URLs, API calls) configurable in settings

---

## 4. Metrics — Real Numbers

KPIs must not just be text descriptions. The framework tracks **actual values**.

### metrics.json structure

```json
{
  "updated_at": "2026-09-07T05:00:00Z",
  "kpis": [
    {
      "name": "Service uptime",
      "target": 99.9,
      "current": 99.2,
      "unit": "%",
      "trend": "down",
      "last_measured": "2026-09-07T04:30:00Z",
      "history": [
        {"date": "2026-09-06", "value": 99.7},
        {"date": "2026-09-05", "value": 99.1}
      ]
    }
  ],
  "goals": [
    {
      "title": "Achieve 99.9% uptime by Q4 2026",
      "status": "on_track",
      "progress_pct": 72
    }
  ]
}
```

- DE updates `metrics.json` at the end of every session
- Portal **dashboard** shows current value vs target with trend indicator (↑ ↓ →)
- Metrics are visible in the profile tab — not just text, actual numbers

---

## 5. Questions to Ask Yourself

At the end of every session, the DE must run a self-evaluation before concluding. These questions are embedded in `job.md` and enforced by the session runner.

**Standard questions (embedded in all job.md templates):**

1. Did I accomplish what was asked of me this session?
2. Are my KPIs moving toward target — or away from it?
3. Is there a follow-up session I should schedule?
4. Did anything happen that my manager would want to know about?
5. Did I hit any guardrail or constraint today?
6. Is my `metrics.json` up to date with current values?

These are not optional. They are part of the completion step of every ReAct loop.

---

## 6. Guardrails — When to Loop in a Human

The DE escalates to human when **any** of these trigger:

| Guardrail | Trigger condition |
|---|---|
| **Level 2 action needed** | Any action in `responsibilities.level_2` |
| **Hard constraint violated** | Any action that would cross a line in `hard_constraints` |
| **Stuck loop** | Same action attempted 3+ times without different result |
| **Unknown situation** | Scenario not covered by job.md and DE cannot determine safe path |
| **Destructive operation** | Delete, overwrite, or modify something that can't be undone |
| **Budget exceeded** | Cost/resource action above defined threshold |
| **External API error** | Unexpected/breaking API response that requires human interpretation |

**How escalation works:**
1. DE calls `request_human_decision(title, description, options, context, urgency)`
2. Portal shows ⏳ badge on DE card + decision card with full context
3. Session pauses (or continues safe fallback while waiting)
4. Human approves/rejects/modifies in portal
5. DE resumes with the decision

---

## 7. Colleague Communication

DEs can work together asynchronously.

```
DE-A (GEO) session runs →
  asks_colleague("cfo", "What's our current monthly AI spend?") →
    CFO inbox gets the question →
      Next CFO session reads inbox →
        report_to_colleague("geo", "Monthly AI spend: $340") →
          GEO picks up reply in its next session
```

- Colleagues are declared in `de.json` (`"colleagues": ["cfo", "shield"]`)
- Communication is via `inbox.jsonl` files (already implemented)
- Portal shows pending colleague messages in profile
- Deadlock guard: max 3 colleague asks per session to prevent loops

---

## 8. Self-Scheduling

A DE can plan its own future work.

```python
schedule_next_session(
    title="Follow-up uptime check after nginx restart",
    when="2026-09-07T08:00:00Z",    # specific time
    trigger_context="Check if nginx is stable after yesterday's restart",
    frequency="once"                  # or daily/weekly
)
```

- Creates entry in `schedule.json`
- **Portal Schedule tab** shows upcoming sessions
- **Cron runner** (to be built) picks up due sessions and triggers them automatically
- DE also schedules based on KPI thresholds (e.g. "if uptime < 99%, check every hour")

---

## 9. Portal — What a Non-Technical Manager Sees

### Sidebar (DE list)
- Name, role, color dot
- Status: 🟢 last session OK / ⏳ waiting for decision / 🔴 error / ⏸ no recent activity
- Pending decisions count badge

### Sessions Panel (left — always visible)
- List of sessions: trigger type, date, duration, quality gate (💡 Value / ✓ Checked / ⚠ No output / ❌ Error)
- Summary snippet from last session
- Click → expanded view (700px)

### Session Steps (expanded)
| Icon | Type | Shows |
|---|---|---|
| 💭 | THINKING | What the DE reasoned |
| ⚡ | ACTION | Tool called + input (compact) |
| 📊 | OBSERVATION | Result of tool (expandable) |
| ⏳ | DECISION | Human approval requested |
| ✅ | COMPLETE | Summary of session |

### Profile Tab (right)
- Mission (full text)
- Goals with progress %
- KPIs with current value vs target + trend arrow
- Responsibilities: L0 / L1 / L2 listed clearly
- Tools enabled (as tags)
- Colleagues network
- Hard constraints

### Settings
- **Full tool list** with enable/disable per DE
- Backend URL + API Token
- Model selection (default: claude-sonnet-4-6)

---

## 10. What Exists vs What's Missing

| Feature | Status | Notes |
|---|---|---|
| ReAct loop (Reason/Act/Observe) | ✅ Working | Anthropic direct API, Sonnet 4.6 |
| Session steps visible in portal | ✅ Working | 💭 ⚡ 📊 ✅ rendered |
| Tools (exec, file, telegram, web, schedule, colleague, decision) | ✅ Working | 8 standard tools |
| DE identity (de.json schema) | ✅ Working | All fields defined |
| Profile tab with responsibilities | ✅ Working | L0/L1/L2 shown if populated |
| KPIs in profile | ✅ Working | Text only — no live numbers yet |
| **Metrics with real numbers** | ❌ Missing | metrics.json empty; DE doesn't write it yet |
| **Goals with progress %** | ❌ Missing | goals field not in de.json yet |
| **Questions to ask yourself** | ⚠️ Partial | In job.md template; not enforced by runner |
| **Tool list in settings (enable/disable)** | ❌ Missing | All DEs get all tools; no per-DE config |
| **Self-scheduling cron runner** | ❌ Missing | schedule.json exists; nothing triggers it |
| **Report to colleague (reply tool)** | ❌ Missing | ask_colleague exists; report_to_colleague not |
| **Dashboard (cross-DE KPI overview)** | ❌ Missing | Only individual DE view exists |
| Session quality gate (auto-assess) | ✅ Working | Value / Checked / No output / Error |
| Drag-to-resize sessions panel | ✅ Working | 420px default, 700px expanded |

---

## Next Build Priorities

1. **metrics.json** — DE writes current KPI values at end of every session → portal shows live numbers
2. **goals field** — add to de.json schema + portal profile display
3. **report_to_colleague tool** — closes the async colleague loop
4. **Tool enable/disable per DE** — in portal settings + session_runner respects it
5. **Self-scheduling cron runner** — background process that polls schedule.json and fires sessions
6. **Dashboard view** — overview of all DEs: status, last session, KPI snapshot
