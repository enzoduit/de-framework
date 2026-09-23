# Pattern: Chief Agent (Jefe Agéntico)

A Chief Agent coordinates multiple specialist DEs toward a shared outcome. It does not do the work directly — it briefs sub-DEs, reads their outputs, and synthesizes decisions for the client.

---

## When Do You Need a Chief Agent?

Use this pattern when:

- **3+ DEs** are working toward one client goal that requires coordination
- Sub-DEs produce **interdependent outputs** (e.g. growth strategy must align with content calendar)
- The client has a "project lead" role in their org chart that primarily routes, reviews, and decides
- You need someone to **consolidate findings** from multiple agents before surfacing to the client

Do NOT create a chief agent if:
- You have ≤2 DEs (just wire them directly)
- DEs are fully independent with no shared outputs
- The "coordination" is just a shared Telegram channel

---

## How a Chief Agent Differs from a Specialist DE

| | Specialist DE | Chief Agent |
|---|---|---|
| **KPIs** | Owns one operational metric (e.g. SoAV, leads) | Coordination KPIs (projects completed, sub-DE waste rate) |
| **Session trigger** | Cron schedule | Weekly or milestone-driven |
| **Primary tool** | External APIs, data files | Shared workspace files, sub-DE outputs |
| **Level 0 authority** | Operational actions | Reading + writing briefs to shared workspace |
| **Level 2 escalations** | Operational blockers | Strategic decisions |
| **Output** | Metrics + experiments log | Weekly summary + decision requests |

---

## Communication: How Chief and Sub-DEs Exchange Information

**Do NOT** use direct API calls or `sessions_spawn` to trigger sub-DEs from the chief. This creates tight coupling and race conditions.

**Use a shared workspace directory instead:**

```
/var/de-agents/<project>/shared/
├── briefs/
│   ├── grow_client--brief--2026-09-23.md    ← chief writes task for sub-DE
│   └── content_agent--brief--2026-09-23.md
├── reports/
│   ├── grow_client--report--2026-09-23.md   ← sub-DE writes its output here
│   └── content_agent--report--2026-09-23.md
└── decisions/
    └── pending--strategy-direction.md        ← waiting for client approval
```

**Flow:**

```
Chief runs (weekly)
  → reads reports/ from last period
  → synthesizes findings
  → writes new briefs/ for each sub-DE
  → creates pending decisions if needed
  → sends summary to client channel

Sub-DE runs (its own cron schedule)
  → reads its latest brief from shared/briefs/
  → executes work
  → writes output to shared/reports/
  → updates its own workspace/experiments.md
```

The chief never blocks waiting for a sub-DE. It reads whatever report was last written.

---

## KPIs for a Chief Agent

Chief agents track coordination quality, not operational metrics:

```yaml
de: "<project>_chief"
kpis:
  - id: projects_completed_this_month
    name: "Projects Completed This Month"
    measure: "python3 workspace/measure_projects.py --metric completed --period month"
    unit: "projects"
    direction: "up"
    target: null
    target_auto: true
    target_improvement: 0.10
    frequency: monthly

  - id: sub_de_waste_rate
    name: "Sub-DE Waste Rate (sessions with no output)"
    measure: "python3 workspace/measure_waste.py"
    unit: "%"
    direction: "lower_is_better"
    target: 20
    frequency: weekly

  - id: decisions_pending
    name: "Pending Client Decisions"
    measure: "python3 -c \"import json, glob; d=json.load(open('shared/decisions/pending.json')) if __import__('os').path.exists('shared/decisions/pending.json') else {}; print(len(d.get('decisions', [])))\""
    unit: "decisions"
    direction: "lower_is_better"
    target: 3
    frequency: per_session
```

---

## Chief Agent job.md Template

```markdown
# <PROJECT>_CHIEF — Project Director

**Mission:** Coordinate the <project> digital team toward <primary client outcome>.

**KPIs:**
- Projects completed per month (target: auto-baseline + 10%)
- Sub-DE waste rate (target: ≤20%)
- Pending decisions (target: ≤3)

**Workspace:** `/var/de-agents/<project>_chief/workspace/` — read at session start.
**Shared workspace:** `/var/de-agents/<project>/shared/` — coordination hub with sub-DEs.

---

## STEP 0 — Read trigger_type. Your scope depends entirely on why you were called.

**No trigger → do not run.**

---

## SESSION TYPE: `cron` — Weekly Coordination (max 8 iterations)

1. Read `shared/reports/` — what did each sub-DE do this period?
2. Identify gaps: which sub-DE produced no report? Which KPI is off track?
3. Write new briefs to `shared/briefs/<de_name>--brief--<date>.md`:
   - One focused task per sub-DE
   - Include: context (1 sentence), desired output format, deadline
4. If a strategic decision is needed → write to `shared/decisions/pending.json` + notify client
5. Write weekly summary to `workspace/weekly-summary.md`
6. Done. Do not do the sub-DEs' work yourself.

---

## SESSION TYPE: `user` — Direct Request (max 10 iterations)

Do what was asked. If the request belongs to a sub-DE → write a brief for that DE instead
of doing the work directly.

---

## Authority levels

**Level 0 — do immediately:**
- Read any sub-DE report or brief
- Write briefs to shared/briefs/
- Write weekly summary
- Write pending decisions to shared/decisions/

**Level 1 — do it, log to workspace:**
- Escalate a sub-DE blocker to client channel
- Change brief scope for a sub-DE

**Level 2 — create decision, stop, wait:**
- Change the primary outcome metric for the project
- Add or remove a sub-DE from the team
- Approve budget spend > [client-defined threshold]
- Anything not explicitly in Level 0/1

**Never:**
- Execute operational work that belongs to a sub-DE
- Create more than 1 pending decision per session
- Trigger sub-DEs directly via API calls
```

---

## Directory Setup for a Chief Agent

```bash
# Chief agent directories
mkdir -p /var/de-agents/<project>_chief/{workspace,logs,sessions}

# Shared coordination hub (separate from individual DE dirs)
mkdir -p /var/de-agents/<project>/shared/{briefs,reports,decisions}

# Initialize shared decision file
echo '{"decisions": []}' > /var/de-agents/<project>/shared/decisions/pending.json
```

---

## Sub-DE Integration: Reading the Brief

Each sub-DE's `job.md` should include a step that reads its latest brief:

```markdown
## STEP 0.5 — Check for Chief Brief (before executing duties)

1. Look for latest brief: `shared/briefs/<de_name>--brief--*.md`
   - If found and newer than last session → this is your primary task this session
   - If not found → proceed with normal cron duties
2. After completing brief task → write report to `shared/reports/<de_name>--report--<date>.md`
```

And each sub-DE's `job.md` header should declare its chief:

```markdown
**Reference Chief:** `/var/de-agents/<project>_chief/` — reads your reports weekly.
```
