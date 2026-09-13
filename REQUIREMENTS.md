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
