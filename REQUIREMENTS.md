# DE Framework — Requirements

Living document. Every decision goes here. Nothing deleted — only amended or marked changed.

**Project started:** 2026-09-08
**Last updated:** 2026-09-13

---

## What It Must Do (Core Requirements)

### 1. Digital Employees are autonomous agents, not chatbots
- Each DE executes work via the **ReAct loop** (think → act with tools → observe → repeat)
- Sending a prompt to a DE triggers **full autonomous execution**, not a Q&A reply
- DEs work without human involvement until they hit a decision gate or finish
- Same behavior whether triggered by schedule, chat, or colleague

### 2. Each DE has a defined identity and mission
- Name, role, mission statement
- KPIs with targets (auto-generated at creation, role-based)
- Guardrails (what it must/must not do)
- Tool access (role-based subset + custom tools)
- Schedules (auto-generated at creation, role-based)
- **Workspace** (files, context, memory) — see §7

### 3. Fixed safety tools — always present, non-removable
- `request_human_decision` — gates on anything requiring human approval
- `ask_colleague` — cross-DE communication
- `report_to_colleague` — sending results upstream

### 4. Quality assurance before reporting to human
- Every DE must run a self-QA step as the final step of any session
- QA checklist (in system prompt): Did I complete the task? Is the output correct? Any errors?
- Goal: save human time and attention — only escalate if output is verified

### 5. KPI tracking over time
- `write_metric` tool available to all DEs
- Metrics tab in portal shows current value, target, trend, history
- DEs instructed to write KPIs at session end

---

## Output Types — Core Design Pattern

Not all agent outputs are equal. The system distinguishes three types with different UX and different human-response options. **This is the most important design pattern in the framework.**

The human's attention is a scarce resource. The output type determines whether and how to consume it.

### 🔔 Decision (the agent is waiting)

The agent cannot proceed without human input. It has hit something outside its authority.

**When to create a Decision:**
- Budget or strategy choice needed
- Action would write to external systems (send email, pause campaign, spend money)
- Risk or anomaly requiring approval

**Human response options:**
- ✅ **Continue** — go ahead
- 💬 **Feedback + Continue** — free-text context, agent integrates it and proceeds
- 🛑 **Stop** — cancel with reason

**Technically:** Session is live, waiting. Response goes as a message into the running session → agent integrates and executes.

---

### 📄 Document (the agent delivered something)

The agent finished a piece of work and is handing it off. It is NOT waiting.

**Examples:** Q4 strategy proposal, weekly report, email draft, analysis

**Human response options:**
- 👍 **Useful** — signal: "keep going, exactly what I need"
- 💬 **Could be better:** ___ — free-text feedback → written to DE's `memory.md` → next document improves

**Important:** "Stop" on a Document makes no sense. The agent is not waiting. Binary Approve/Reject is wrong here (see below).

---

### 📊 Insight (the agent is informing, no action needed)

The agent has information the human should know. No action required, no waiting.

**Examples:** Spend anomaly, open rate drop, trend from social listening

**Human response options:**
- ✓ **Seen** — acknowledged
- ❓ **What do I do with this?** — opens chat with the DE for further explanation

**Important:** Insights inform, they don't block. They appear as notifications, not blocking modals.

---

### Why Binary Approve/Reject is wrong

The classic Approve/Reject pattern doesn't fit this kind of AI work:

- **Approve** implies: "I authorized exactly this" — but often the human means "yes, but focus on donors over 2 years"
- **Reject** implies: "never do this" — but often means "not this time, try differently"
- No channel for nuance or context

**Right:** Free-text response. The human writes "continue but focus on donors over 2 years" → goes as a message into the session → agent integrates and executes.

---

## Human Attention Principle

The human is not a reviewer of every step — they are a manager whose attention is a scarce resource. Design every output, notification, and escalation with this in mind.

**The 4 reasons a DE should contact a human:**

| # | Trigger | Example |
|---|---------|--------|
| 1 | Decision outside its authority | "Should I pause the campaign?" |
| 2 | Deliverable finished | "Here's the Q4 report" |
| 3 | Anomaly/risk the human MUST know | "Spend +40% in 2h" |
| 4 | Blocked, needs direction | "I have no data for this period" |

**Everything else:** resolve itself or message a colleague DE.

**Noise reduction without a manager layer:**
1. Output types (Decision/Document/Insight) — halves noise immediately
2. Preference memory per DE — after 3 identical rejections, stop asking
3. Priority/urgency — only push notifications for critical items
4. DE-to-DE direct via `inbox.jsonl` — no manager as middleman

---

## Autonomy Level Progression

DEs start in **Validation Mode** — everything escalates to the human as a Decision. No autonomous external actions.

With track record, autonomy increases:

| Level | What the human sees |
|-------|-------------------|
| **1 (Validation)** | Everything — every action, every output |
| **2** | Only Decisions and critical Insights |
| **3** | Only Decisions above a defined threshold |

**Transition:** Manual — the human decides when trust is established. The DE does not self-promote.

**Preference memory per DE:**
- Which output types are accepted
- Which format preferences the human has
- After 3 identical rejections of the same type → DE stops asking, delegates differently

---

## Portal Requirements

### Mobile
- 4 tabs always visible: **SESSIONS | PROFILE | SCHEDULE | METRICS** (+ WORKSPACE when built)
- Content below the tab bar changes based on selected tab
- No split-pane on mobile — tabs replace the left panel entirely
- Desktop: split-pane (sessions list left, detail panel right)

### White-label
- Branding configurable: logo, company name, accent color
- Via portal settings, API, or pre-deploy HTML variable
- Default: empty URL → settings dialog opens on first visit

### Language
- English throughout — no German strings in UI

### Key flows that must work
- [ ] Select DE → see sessions
- [ ] Click SESSIONS tab → see session list and RUN button; tab bar stays visible
- [ ] Click PROFILE tab → see DE profile (role, mission, tools)
- [ ] Click SCHEDULE tab → see schedules; + Add Schedule button always visible
- [ ] Click METRICS tab → see KPI cards with current value + history
- [ ] Click WORKSPACE tab → see files; create/upload; preview content (to build)
- [ ] Send message → triggers full ReAct loop → session appears with step trace
- [ ] Click RUN → same as send message with default daily briefing prompt

---

## Tool System Requirements

### Core tools (always available)
`exec_shell`, `read_file`, `write_file`, `send_telegram`, `web_search`,
`schedule_next_session`, `ask_colleague`, `report_to_colleague`,
`request_human_decision`, `write_metric`

### Custom tools
- Drop a JSON in `$CUSTOM_TOOLS_DIR` (default: `/var/de-framework-tools/`)
- No restart needed — loaded fresh on each tool discovery call
- Portal shows them with 🔧 CUSTOM badge
- Fields: `id`, `name`, `description`, `script`, `icon`, `required_credentials`

### Credential store
- Credentials encrypted at rest (AES-256 Fernet, key derived from `DE_API_TOKEN`)
- Portal UI: per-tool credential status — ✅ set / ⚠ missing
- Credentials injected as env vars at tool runtime — never in logs

---

## Workspace Requirements (To Build)

**Context:** Each DE must know what work it has done, what it was told, and what relevant files exist. This is the DE's "brain."

### File workspace
- Per-DE directory: `/var/de-agents/{name}/workspace/`
- Portal: **WORKSPACE tab** alongside PROFILE / SCHEDULE / METRICS
- User can: create text files, upload files, drag-and-drop
- DE can: read and write files via `read_file` / `write_file` tools (scoped to its workspace)

### Context loading at session start
- Backend reads workspace files at session start and injects into system prompt
- Priority order: `MEMORY.md` > `README.md` > `TODO.md` > other `.md` files
- Also includes: summaries of last 3-5 sessions (especially human feedback + decisions)
- DE sees this as "Your Workspace Context" — it knows its own state

### MEMORY.md as DE brain
- DE is instructed to write key facts, decisions, progress to its `MEMORY.md`
- This persists across sessions — DE remembers what it learned
- Human can edit `MEMORY.md` directly in portal to steer the DE

---

## Multi-Tenant / Deployment Requirements

### Hosting Architecture

**For demos / development:** Run locally or Render.com (free tier). Render uses ephemeral storage — agents lose memory on redeploy. Acceptable for demos, not for production.

**For production (recommended):** Ubuntu 22.04 LTS VPS + systemd + Caddy
- Persistent disk storage: agents keep memory across deploys and restarts
- systemd: auto-restart on crash
- Caddy: HTTPS + routing, minimal config
- `bootstrap.sh`: one-script setup, idempotent

This is the only deployment mode where the two non-negotiables hold:
1. Portal always loads
2. DE Framework always runs (embedded scheduler, no external cron)

**Container deployments:** Set `CUSTOM_TOOLS_DIR` to a persistent volume path.

---

### Fresh server setup
- `bootstrap.sh` — idempotent, installs everything, creates folder structure
- `SETUP.md` — org chart → DE mapping, end-to-end setup guide
- `DEPLOYMENT.md` — self-hosted / container specific notes

### Configurability (all via env vars or API)
- `CUSTOM_TOOLS_DIR` — default `/var/de-framework-tools`
- `DE_API_TOKEN` — auth for all API calls
- `window.DE_BACKEND_URL` — portal backend URL (pre-configurable in HTML)
- Branding — via `/api/branding` or `/var/de-framework-branding.json`

### Python compatibility
- Must work on Python 3.11+ (Ubuntu 22.04)
- No nested same-quote f-strings

---

## Verification Checklist

Before any deploy, verify each item:

**Core execution**
- [ ] Chat prompt → ReAct loop (not just text answer)
- [ ] Session steps visible in portal in real time
- [ ] Session completes with status `complete`
- [ ] KPIs written at session end via `write_metric`

**Mobile portal**
- [ ] All 4 tabs always visible
- [ ] Switching tabs works from every tab (no dead ends)
- [ ] Add Schedule button visible in empty state
- [ ] Send a message input visible and functional
- [ ] No text/button cut off at bottom

**Tools**
- [ ] Custom tool JSON → appears in portal Tool Library
- [ ] Credential set in portal → injected as env var when tool runs
- [ ] exec_shell works (basic bash command)

**Multi-tenant**
- [ ] bootstrap.sh runs on fresh Ubuntu 22.04 without errors
- [ ] POST /api/des creates a DE with role-based schedules + KPIs
- [ ] git pull + systemctl restart is enough to update

---

## Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-08 | Tools stored as string IDs in de.json, resolved to full dicts at runtime | Keeps de.json human-readable; implementation in tool_discovery.py |
| 2026-09-08 | Fixed tools (request_human_decision, ask_colleague, report_to_colleague) always present with 🔒 | Non-negotiable safety + communication layer |
| 2026-09-08 | Auto-schedules on POST /api/des, role-based | Saves setup time; user can delete unwanted ones |
| 2026-09-08 | Auto-KPIs on POST /api/des, role-based | Same reason; gives every DE a baseline metric set |
| 2026-09-08 | write_metric tool generic (not OPS-specific) | Every DE needs to write its own metrics |
| 2026-09-09 | Credential store: AES-256 Fernet, key derived from DE_API_TOKEN | No extra key file; credentials never in plaintext or logs |
| 2026-09-09 | Custom tools: /var/de-framework-tools/*.json drop-in | No restart required; instant visibility in portal |
| 2026-09-09 | Light theme + white-label branding | Framework is a product for other orgs to deploy |
| 2026-09-13 | CUSTOM_TOOLS_DIR via env var (was hardcoded /var/) | Container deployments need persistent volume path |
| 2026-09-13 | Portal default backend URL = empty string | Self-hosted installs must not default to enzoduit.com |
| 2026-09-13 | Mobile: 4 tabs always visible, content below | Standard native app pattern; split-pane desktop only |
| 2026-09-13 | DE workspace + MEMORY.md + context loading | DEs need persistent memory and file-based context across sessions |
| 2026-09-13 | QA step before reporting to human | Save human time and attention — core design principle |

---

## Quality Baseline — Session Efficiency (Added 2026-09-26)

*Living quality gates. Check against these during every health audit.*

---

### R1 — Session Efficiency by DE Type

| DE Type | Max Steps | Notes |
|---|---|---|
| Monitoring (ops-style) | ≤ 40 | Many services to check; completions are OK |
| Scheduling/Admin (flow, coach) | ≤ 25 | Briefing-driven; no exploration allowed |
| Product/Content (aria, growth) | ≤ 40 | One focused action per session |
| GEO Research (grow_*) | ≤ 30 | Perplexity runs in pre_fetch, NOT in session |
| Security (shield) | ≤ 55 | Deep scan requires more steps |
| Cost Control (max) | ≤ 35 | API + data review |

`max_iterations_reached` = FAILURE state. Acceptable only for growth/shield with explicit budget.

---

### R2 — Session Completion Rate

- **Target:** ≥ 80% `complete` (not `max_iterations` or `error`)
- **Current Baseline (2026-09-26):** ops✅ shield✅ coach✅ growth✅ = 4 of 12 active DEs = 33% → **BELOW TARGET**
- **Systemic failure pattern:** grow_* hitting 43-52 steps due to in-session Perplexity queries

---

### R3 — KPI Measurement

- Every DE must have at least 1 measurable KPI in `kpis.yaml`
- `measure` command must output a number or `not_measured`
- `not_measured` is OK during bootstrap; after 2nd session it is a failure signal
- **Root cause of grow_* overrun:** `measure_soav.py` returning `not_measured` → agent runs full benchmark in session (→ 20+ extra steps)

**Fix applied 2026-09-26:**
- `measure_soav.py` updated for grow_flyraising, grow_agentfabric, grow_engelreal to read from `/root/.openclaw/workspace/agents/{de}/soav_history.json`

---

### R4 — pre_fetch Pipeline

- `pre_fetch.py` MUST run successfully before every session
- If pre_fetch fails → session MUST abort (not run without briefing)
- **grow_* pre_fetch must cache Perplexity benchmark** (max 6h old) before session starts

**Fix applied 2026-09-26:**
- `run_benchmark_if_stale()` function added to all 5 grow_* `pre_fetch.py` files
- Calls `benchmark_v2.py` or `geo_benchmark.py` when soav data is > 6h old
- 5-minute timeout; failure is non-fatal (continues with cached data)

---

### R5 — STOP Block Specificity

Every DE job.md MUST have STOP block with:
1. HARD tool call limit (not just "max N iterations")
2. Concrete DONE definition: "DONE = [specific file] updated"
3. Explicit "DO NOT" list for common rabbit holes

**Weak (old):** "max 5 iterations, stop after KPI check"
**Strong (new):** "HARD LIMIT: max 4 tool calls. DONE = workspace/log.md updated. DO NOT re-investigate KPI calculations."

**Fixed 2026-09-26:** flow, aria, growth, grow_agentic_living, growed, grow_flyraising, grow_agentfabric, grow_engelreal

---

### R6 — Service Monitoring (OPS)

- OPS must run every 2h (cron: `0 */2 * * *`)
- OPS target: ≤ 40 steps (monitoring 5+ services)
- Monitored: de-backend, krisp-proxy, nginx, pendant-backend (canvas-server: excluded)
- Real performance 2026-09-26: 27-34 steps → **WITHIN TARGET**

---

### R7 — Human Decision Channel

- Level 2 decisions MUST reach portal inbox
- Delivery: Portal-first (Decisions API: `http://localhost:8766`)
- Telegram: secondary channel only for urgent/real-time alerts

---

## DE Inventory — Expected Behavior (2026-09-26)

| DE | Schedule | Expected Steps | Last Session | Last Status | Last Steps |
|---|---|---|---|---|---|
| ops | every 2h | ≤ 40 | 2026-09-26 | ✅ complete | 34 |
| shield | daily 07:00 | ≤ 55 | 2026-09-26 | ✅ complete | 36 |
| max | daily 06:00 | ≤ 35 | 2026-09-26 | ⚠️ max_iter | 39 |
| flow | daily 08:00 | ≤ 25 | 2026-09-26 | ❌ max_iter | 46 |
| coach | daily 08:30 | ≤ 30 | 2026-09-26 | ✅ complete | 29 |
| aria | Mon+Thu 09:00 | ≤ 40 | 2026-09-24 | ❌ max_iter | 65 |
| growth | weekly Mon 09:00 | ≤ 40 | 2026-09-24 | ✅ complete | 22 |
| grow_agentic_living | every 2 days 10:00 | ≤ 30 | 2026-09-24 | ❌ max_iter | 52 |
| growed | every 2 days 10:00 | ≤ 30 | 2026-09-24 | ❌ max_iter | 45 |
| grow_flyraising | every 2 days 11:00 | ≤ 30 | 2026-09-24 | ❌ max_iter | 49 |
| grow_agentfabric | every 2 days 09:00 | ≤ 30 | 2026-09-26 | ❌ max_iter | 43 |
| grow_engelreal | every 2 days 11:00 | ≤ 30 | 2026-09-24 | ❌ max_iter | 50 |

---

## Health Check Commands

```bash
# Quick status check — all DEs
for de in ops shield max flow coach aria growth grow_agentic_living growed grow_flyraising grow_agentfabric grow_engelreal; do
  last=$(ls /var/de-agents/$de/sessions/ws-${de}-2026*.json 2>/dev/null | sort | tail -1)
  if [ -z "$last" ]; then echo "$de: no session"; continue; fi
  python3 -c "
import json
d=json.load(open('$last'))
steps=d.get('steps',[])
actions=sum(1 for s in steps if s.get('type')=='action')
print(f'$de: {d[\"status\"]} ({len(steps)} steps, {actions} actions)')
"
done

# pre_fetch smoke test for each grow_* agent
for de in grow_agentic_living growed grow_flyraising grow_agentfabric grow_engelreal; do
  echo -n "$de pre_fetch soav: "
  python3 /var/de-agents/$de/workspace/measure_soav.py 2>/dev/null || echo "ERROR"
done

# Service health
curl -s http://localhost:8769/health && echo " ← de-backend OK" || echo "de-backend DOWN"
curl -s http://localhost:8770/health && echo " ← krisp-proxy OK" || echo "krisp-proxy DOWN"
```

---

## Known Issues & Mitigations (2026-09-26)

| Issue | Root Cause | Fix Applied | Date | Status |
|---|---|---|---|---|
| canvas-server 40+ wasted steps | Wrong KPI in ops kpis.yaml | Removed from kpis.yaml + pre_fetch.py | 2026-09-23 | ✅ FIXED |
| grow_flyraising/agentfabric/engelreal not_measured | measure_soav.py wrong path | Updated measure_soav.py fallback paths | 2026-09-26 | ✅ FIXED |
| grow_* 43-52 steps | Perplexity queries run in session | pre_fetch.py now calls benchmark if stale | 2026-09-26 | ✅ APPLIED |
| flow 46 steps, max_iterations | STOP block too generic, agent investigates KPI source | Specific done-condition + 4-tool hard limit | 2026-09-26 | ✅ FIXED |
| aria 65 steps, max_iterations | No STOP block at all | Full STOP block added | 2026-09-26 | ✅ FIXED |
| grow_* 43-52 steps (underlying) | Perplexity API key expired (401) | Needs new API key in job.md | 2026-09-26 | ⚠️ OPEN |
| max 39 steps, max_iterations | STOP block may need tightening | Not yet investigated | 2026-09-26 | ⚠️ OPEN |

---

## Decision Log (continued from above)

| Date | Decision | Reason |
|---|---|---|
| 2026-09-26 | grow_* STOP block: hard 10-tool limit + "DO NOT run Perplexity in session" | Root cause of 43-52 step runs; Perplexity belongs in pre_fetch |
| 2026-09-26 | pre_fetch.py: run_benchmark_if_stale() for all grow_* | Moves Perplexity benchmark out of ReAct loop; reduces session steps by ~20 |
| 2026-09-26 | measure_soav.py: fallback to agent workspace soav_history.json | Fix not_measured for grow_flyraising/agentfabric/engelreal |
| 2026-09-26 | ARIA: added full STOP block | Had NO STOP block — sessions ran 65 steps without limit |
| 2026-09-26 | FLOW: hard 4-tool limit + explicit done-condition | Was investigating KPI source for 40+ steps; brief was enough |

---

## User Experience & Portal Requirements
*Added: 2026-09-26*

### R-DATA1 — User Input Persistence (CRITICAL)
Every user input — decisions, feedback, chat messages — MUST be:
- Saved to disk before processing (raw, immutable)
- Stored in `<de-dir>/user_inputs/YYYY-MM-DD-HH-MM-<type>.json`
- Never deleted automatically
- Available for learning pipelines

```json
{
  "timestamp": "ISO",
  "type": "decision|feedback|chat|annotation",
  "session_id": "ws-...",
  "de": "ops",
  "raw_input": "...",
  "context": { "decision_id": "...", "file": "..." }
}
```

### R-DATA2 — DE Learning from User Feedback
When a user provides feedback or makes a decision:
1. Input MUST be saved (R-DATA1)
2. If feedback is actionable → DE's `memory.md` and/or `job.md` MAY be updated
3. All updates attributed (what changed, why, which user input triggered it)
4. Learning is scoped to the DE's domain — never absorbs another DE's function

### R-UX1 — Decision Flow Visualization
- Portal MUST show visually where human was looped in
- Decision card shows: original agent question + human answer + agent continuation
- Session timeline shows: [Agent working] → [⏸ Waiting for human] → [✅ Human decided: "X"] → [Agent continuing]
- User must be able to navigate to the full session post-decision

### R-UX2 — File Feedback Pattern
When an agent requests feedback on a document/file:
- Output MUST be a file in `<de-dir>/workspace/outputs/<filename>` (never ephemeral)
- File MUST include references (where data came from, what sources were used)
- Portal shows the file with: open | annotate | delete | send back to agent
- User can delete the file — agent receives deletion as signal to regenerate or drop

### R-UX3 — Update Notifications (Closeable)
Agent updates (non-decision outputs) MUST be:
- Dismissible: user can close without action
- Followable: user can click "Follow up" → opens conversation with that DE
- Archived: closed updates stay in history, not deleted

### R-UX4 — Direct DE Chat
Portal MUST support direct message to any DE:
- Identical to sending a Telegram message to the agent
- DE receives message with its full context (role, mission, tools defined in job.md)
- Response appears in portal chat view
- Chat history saved to `<de-dir>/user_inputs/`

### R-UX5 — Tool Management
- Portal MUST show tool inventory per DE (what tools are enabled in job.md)
- Adding a tool: user types "add [tool_name] to [DE]" in interface → agent updates job.md
- Tool additions require human confirmation before taking effect
- Tool list sourced from framework's `docs/runtime-environment.md`

### R-UX6 — Cost Overview per DE
- Portal MUST show cost per DE: total tokens, estimated cost (USD), breakdown by session
- Ability to view and delete scheduled cron tasks per DE directly from cost view
- "This DE costs $X/month at current cadence" visible at a glance
- Cost data sourced from session JSON files (steps × model pricing)

### R-FRAMEWORK1 — Terminology File (Per Organization)
Every DE deployment MUST include a `terminology.md` in the shared workspace:
- Defines how the organization understands key terms (e.g., "lead", "conversion", "churn")
- Defines exactly how each KPI is measured (formula, data source, frequency)
- DEs MUST reference this file when interpreting data — never invent definitions
- Updated when org changes how they define things
- Template: `templates/terminology.md` in the framework repo

### R-FRAMEWORK2 — Recommendations Transparency
All agent recommendations MUST include:
- The data/evidence it's based on
- The reasoning chain (not just the conclusion)
- Confidence level (high/medium/low)
- What the agent would need to be more certain

