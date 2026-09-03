# Digital Employees Framework

Run autonomous AI agents with defined missions, KPIs, and approval gates — powered by Claude (Anthropic API).

Each **Digital Employee** knows what it owns, what it can do without asking, what it should document, and what it must ask you before doing. It runs on a schedule or on demand, logs every step as a **Work Session**, and pauses for human decisions when it hits something risky.

---

## What you're hosting

```
┌──────────────────────────────────────────────────────────────────┐
│  PORTAL (Cloudflare Pages — static, free)                        │
│  Single HTML file. Shows your DEs, their sessions, decisions.    │
│  Talks to the backend via API calls (uses your API token).       │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP + Bearer token
┌────────────────────────▼─────────────────────────────────────────┐
│  BACKEND (Python — you host this)                                │
│  REST API, port 8766. ReAct engine. Session persistence.         │
│  Reads/writes from AGENTS_DIR (folder with your DE configs).     │
│  Needs: Python 3.10+, anthropic package, ANTHROPIC_API_KEY       │
└──────────────────────────────────────────────────────────────────┘
```

**Security model:** The backend should NOT be publicly accessible without auth. Every API call requires `Authorization: Bearer <DE_API_TOKEN>`. In production, put it behind HTTPS (Render/Railway handle this automatically).

---

## Quick start (5 minutes)

### 1 — Clone and install

```bash
git clone https://github.com/enzoduit/de-framework.git
cd de-framework
pip install -r requirements.txt
```

### 2 — Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...        # required
DE_API_TOKEN=choose-a-secret-token  # required — portal uses this to authenticate
AGENTS_DIR=./agents                 # where DE configs live (auto-created)
DE_MODEL=claude-haiku-4-5           # cheap + fast for autonomous runs
DE_API_PORT=8766                    # default port
```

### 3 — Start the backend

```bash
source .env && python backend/server.py
# → Running on http://localhost:8766
```

### 4 — Open the portal

Open `portal/index.html` in a browser. Click ⚙ (bottom of sidebar) and enter:
- Backend URL: `http://localhost:8766`
- Token: your `DE_API_TOKEN`

### 5 — Create your first Digital Employee

Click **+ NEW** in the sidebar. The AI wizard collects mission, KPIs, autonomy levels, and schedule — then generates `de.json` and `job.md` automatically.

---

## Deploying the backend (pick one)

### Option A — Render.com (recommended for quick demo)

`render.yaml` is already in the repo. Deploy in 4 clicks:

1. Fork `enzoduit/de-framework` to your account
2. Go to [render.com](https://render.com) → New → Web Service → Connect your fork
3. Render reads `render.yaml` automatically (Python, `pip install -r requirements.txt`, `bash start.sh`)
4. Add environment variables in Render dashboard:

| Key | Value |
|-----|-------|
| `ANTHROPIC_API_KEY` | your key |
| `DE_API_TOKEN` | a secret you choose |
| `AGENTS_DIR` | `/tmp/de-agents` (ephemeral — see note below) |
| `DE_MODEL` | `claude-haiku-4-5` |

5. Deploy → copy the `https://....onrender.com` URL → paste into portal ⚙ settings

> ⚠️ **Persistence note:** Render free tier uses ephemeral storage. `/tmp/de-agents` is wiped on redeploy. For persistent agents and sessions, use a paid Render disk, Railway volume, or self-host on a VPS with a permanent path.

### Option B — Railway

```bash
# 1. Install Railway CLI
npm install -g @railway/cli
railway login

# 2. Create project
railway init

# 3. Set env vars
railway variables set ANTHROPIC_API_KEY=sk-ant-...
railway variables set DE_API_TOKEN=your-secret
railway variables set AGENTS_DIR=/data/agents
railway variables set DE_MODEL=claude-haiku-4-5

# 4. Deploy
railway up
# → Get your URL from Railway dashboard
```

Add a Railway Volume at `/data/agents` for persistent storage.

### Option C — Self-host (VPS / your server)

```bash
# Install as a systemd service (Linux)
sudo cp deploy/de-framework.service /etc/systemd/system/
sudo systemctl enable de-framework
sudo systemctl start de-framework
```

Or run directly with a process manager:

```bash
# Using pm2
npm install -g pm2
pm2 start "python backend/server.py" --name de-framework
pm2 save
```

Put Nginx in front for HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name your-backend-domain.com;
    
    location / {
        proxy_pass http://localhost:8766;
        proxy_set_header Authorization $http_authorization;
    }
}
```

### Option D — Docker

```bash
docker build -t de-framework .
docker run -d \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e DE_API_TOKEN=your-secret \
  -e AGENTS_DIR=/data/agents \
  -v /path/to/your/agents:/data/agents \
  -p 8766:8766 \
  de-framework
```

---

## Deploying the portal (Cloudflare Pages)

The portal is a single HTML file — deploy it anywhere static hosting works.

```bash
# Cloudflare Pages (recommended — free, global CDN)
npx wrangler pages deploy portal/ --project-name my-de-portal
```

Then in Cloudflare Pages dashboard → Settings → Environment Variables:
- `DE_API_URL` = your backend URL (e.g. `https://my-de.onrender.com`)
- `DE_API_TOKEN` = your token

> **Local dev:** Just open `portal/index.html` directly in a browser. No server needed.

---

## UI layout

```
┌──────────────┬────────────────────────────────────────────────┐
│              │ LEFT PANEL (resizable)  │ RIGHT PANEL           │
│   SIDEBAR    │─────────────────────────│────────────────────── │
│              │                         │                        │
│  ⚡ Max       │  ⏰ SCHEDULED  💡 Value │  💬 CHAT              │
│  CFO         │  Checked costs. Found   │  ℹ PROFILE            │
│              │  3 savings opps.        │  📅 SCHEDULE          │
│  ⚡ Flow      │  2h ago · 12 steps     │                        │
│  Ops         │─────────────────────────│  Right panel shows    │
│              │  👤 USER   ✓ Checked    │  DE details, chat,    │
│  + NEW       │  Manual run triggered   │  schedule, decisions  │
│              │  just now · 3 steps ●   │                        │
│  ⏳ 2 decs   │─────────────────────────│  Drag the divider ←→  │
└──────────────┴─────────────────────────┴────────────────────── ┘
```

**Left panel — Work Sessions** (always visible):
- Lists every session for the selected DE
- Trigger badge: `⏰ SCHEDULED` / `🧑 USER` / `💬 CHAT` / `👥 COLLEAGUE` / `📊 AUTO`
- Quality gate: `💡 Value created` / `✓ Checked` / `⚠ No output` / `❌ Error`
- Click any session → see a **timeline** of what the agent did, in plain language

**Right panel — DE Detail** (tabs):
- **Profile**: mission, KPIs, autonomy levels, responsibilities
- **Chat**: talk to the DE directly — triggers a live session, shows steps in real time
- **Schedule**: scheduled activities + upcoming runs

**Decisions drawer** (bottom of sidebar): pending Level 2 approvals across all DEs

---

## Creating a Digital Employee

### Via the portal wizard (recommended)

Click **+ NEW** → the AI chat wizard collects:
1. Name and role
2. Mission statement + KPIs
3. Autonomy levels (what it can do at each level)
4. Success criteria + run schedule
5. Autoresearch queries (optional)

Generates `de.json` and `job.md` automatically.

### Manually (files)

Create a folder under `AGENTS_DIR`:

```
agents/
  my-agent/
    de.json       ← profile + config
    job.md        ← mission brief (system prompt for the ReAct engine)
    memory.md     ← persistent long-term memory (auto-updated)
    metrics.json  ← KPI snapshots (auto-updated)
    decisions.json ← approval queue
    sessions/     ← one JSON per run (step-by-step replay)
    schedule.json ← planned activities
    workspace/    ← agent's working files
    inbox.jsonl   ← messages from colleague DEs
```

**`agents/my-agent/de.json`**:

```json
{
  "name": "my-agent",
  "display_name": "MY AGENT",
  "role": "What this agent does in one line",
  "color": "#FF4500",
  "mission": "Own X, deliver Y, measure Z.",
  "kpis": ["Weekly cost stays under $500", "Zero unreviewed incidents"],
  "responsibilities": {
    "level_0": ["Read metrics and logs"],
    "level_1": ["Write to workspace files", "Deploy static pages"],
    "level_2": ["Disable services", "Send external communications"]
  },
  "hard_constraints": ["Never access billing credentials"],
  "data_sources": ["http://localhost:3002/api/summary"],
  "self_evaluation": {
    "criteria": ["Cost stayed within budget for 7 consecutive days"],
    "schedule": "daily"
  },
  "triggers": [
    {"type": "cron", "schedule": "Daily 08:00 UTC"},
    {"type": "user", "description": "On-demand via portal"}
  ],
  "model": "claude-haiku-4-5",
  "max_iterations": 8
}
```

**`agents/my-agent/job.md`** — write this like a job description. The ReAct engine reads it as the system prompt:

```markdown
# MY AGENT — Mission Brief

## Mission
[One paragraph: what you own, what success looks like]

## KPIs
- KPI 1
- KPI 2

## Autonomy
### Level 0 — Do immediately, no notification
- [List actions]

### Level 1 — Do it, then document in portal
- [List actions]

### Level 2 — Stop and ask first
Call `request_human_decision` with title, description, and proposed action.

### Never
- [Hard constraints]

## Tools available
- `read_file(path)` — read from workspace
- `write_file(path, content)` — write to workspace
- `http_get(url)` — fetch external data
- `http_post(url, data)` — POST to an API
- `exec_command(cmd)` — run shell command (Level 1+)
- `request_human_decision(title, description, proposed_action)` — Level 2 gate
- `ask_colleague(colleague_name, message)` — ask another DE (max 3× per session)
- `schedule_next_activity(description, when)` — plan a future session
- `update_metrics(data)` — write to metrics.json
- `update_memory(content)` — append to memory.md

## Data sources
Check these on every run: [list URLs or file paths]

## Self-evaluation
After every session, ask: did I create value? If not, log why.
```

---

## How sessions work

```
Trigger (user / cron / colleague)
  └─ session_runner.py creates sessions/<id>.json
      └─ ReActEngine.run() starts the loop:
          OBSERVE  → read state (metrics.json, memory.md, data sources)
          REASON   → Claude chooses next action
          ACT      → execute tool
          OBSERVE  → tool result back into context
          REPEAT   → until done, max_iterations, or decision needed
              │
              └─ if request_human_decision():
                    status = "paused_human"
                    decision → decisions.json + portal queue
                    human approves/rejects → session resumes
```

**Session ID format:** `ws-{de_name}-{YYYYMMDD-HHMMSS}-{6char_hex}`

**Session file structure:**
```json
{
  "id": "ws-cfo-20260903-080012-a3f9b2",
  "de_name": "cfo",
  "trigger_type": "cron",
  "status": "complete",
  "created_at": "2026-09-03T08:00:12Z",
  "duration_seconds": 43,
  "steps": [
    {"type": "trigger", "content": "Daily 08:00 UTC run", "ts": "..."},
    {"type": "reasoning", "content": "I should check metrics first...", "ts": "..."},
    {"type": "action", "tool": "read_file", "input": "metrics.json", "ts": "..."},
    {"type": "observation", "result": "{\"daily_cost\": 412}", "ts": "..."},
    {"type": "complete", "summary": "Cost is $412, within budget.", "ts": "..."}
  ],
  "summary": "Cost is $412, within budget. No action needed."
}
```

**Quality gate** (shown in portal UI):
- `💡 Value created` — session called at least one action tool or raised a decision
- `✓ Checked` — session ran and produced a summary but took no action
- `⚠ No output` — session completed with no summary (likely a short-circuit or error)
- `❌ Error` — session failed

---

## Autonomy levels

| Level | Behavior | Example |
|-------|----------|---------|
| **0** | Act silently, no record in portal | Read files, ping endpoints |
| **1** | Act + document (logged in session, visible in portal) | Deploy a page, write a report |
| **2** | Pause + ask human first | Disable a service, spend money |

Level 2 flow: agent calls `request_human_decision(title, description, proposed_action)` → session status → `paused_human` → appears in portal Decisions drawer → you approve/reject → session auto-resumes via `/de-start --resume`.

---

## Colleagues (agent-to-agent)

Add `"colleagues": ["other-agent"]` in `de.json`. The agent can then call `ask_colleague("other-agent", "message")`.

This drops a message in `agents/other-agent/inbox.jsonl`. The other DE picks it up on its next cron run (or you can trigger it manually).

**Deadlock guard:** Max 3 calls to the same colleague per session.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `DE_API_TOKEN` | ✅ | — | Auth token for all API calls |
| `AGENTS_DIR` | ✅ | `./agents` | Root directory for all DE folders |
| `DE_MODEL` | — | `claude-haiku-4-5` | Default model (override per-agent in `de.json`) |
| `DE_MAX_ITERATIONS` | — | `8` | Max ReAct loop iterations |
| `DE_API_PORT` | — | `8766` | Backend port |
| `DECISIONS_API_URL` | — | — | External webhook for decision notifications |
| `TELEGRAM_BOT_TOKEN` | — | — | Telegram notifications |
| `TELEGRAM_NOTIFY_CHAT_ID` | — | — | Telegram chat ID |

---

## API reference

All endpoints require `Authorization: Bearer <DE_API_TOKEN>`.

### DE management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/de-list` | List all DEs with pending decision count |
| `GET` | `/de/<name>` | Get DE profile (de.json) |
| `POST` | `/de/create` | Create DE from config object |
| `GET` | `/de/<name>/sessions` | List all sessions for a DE |
| `GET` | `/de/<name>/sessions/<id>` | Get full session (steps + status) |
| `GET` | `/de/<name>/schedule` | Get schedule.json |
| `GET` | `/de/<name>/workspace` | List workspace files |
| `GET` | `/health` | Health check (no auth required) |

### Session control

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/de-start` | `{de_name, trigger_type, trigger_context?}` | Start a new session |
| `POST` | `/de/<name>/sessions/start` | `{trigger_type, trigger_context?}` | Same, DE in path |

### Decisions

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `GET` | `/decisions` | — | All pending decisions |
| `POST` | `/decide` | `{session_id, decision_id, decision: "approve"\|"reject", reason?}` | Resolve a decision |

### Setup

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/signup` | AI-powered DE creation from natural language description |

---

## Extending

**Add a tool:**
```python
# In session_runner.py, add to the tools list:
{
    "name": "my_tool",
    "description": "What it does",
    "input_schema": {"type": "object", "properties": {"param": {"type": "string"}}},
    "fn": lambda input_data: my_tool_implementation(input_data["param"])
}
```

**Add a trigger type:**
- Add the trigger type string to `de.json → triggers`
- Call `/de-start` with `trigger_type: "my-trigger"` from your external system

**Custom session runner:**
```python
from backend.core.work_session import WorkSession
from backend.core.react_engine import ReActEngine

session = WorkSession(de_name="my-agent", trigger_type="custom", agents_dir=AGENTS_DIR)
engine = ReActEngine(job_md=job_md, tools=tools, session=session, model=MODEL)
result = engine.run(trigger_context="custom trigger context")
```

---

## For agents reading this repo

If you're an AI agent looking to spin up Digital Employees for a new user:

1. **Clone the repo** to the user's workspace
2. **Check `backend/server.py` runs** — `python backend/server.py`  
3. **Create `AGENTS_DIR`** (default `./agents`) — this is where all DEs live
4. **Call `POST /signup`** with a natural language description of what DE to create, or create `de.json` + `job.md` files manually in `agents/<name>/`
5. **Start sessions** via `POST /de-start` or via portal chat
6. **Monitor sessions** via `GET /de/<name>/sessions` — check `status` field and `summary`
7. **Resolve decisions** via `POST /decide` when sessions are `paused_human`

The portal is optional — everything works via API. The portal just makes it visual.

**Key invariant:** Every session file in `agents/<name>/sessions/` is a complete, self-contained record of what happened. Sessions are append-only. The agent never modifies or deletes past sessions.

---

## Architecture

```
de-framework/
├── backend/
│   ├── server.py               Entry point — HTTP server
│   ├── config.py               All config from environment variables
│   ├── core/
│   │   ├── react_engine.py     ReAct loop (Observe → Reason → Act)
│   │   ├── session_runner.py   Spawns ReAct engine per trigger
│   │   └── work_session.py     Session file manager (read/write steps)
│   └── routes/
│       ├── de_routes.py        /de-list, /de/<name>, /de/create, ...
│       ├── decisions_routes.py /decisions, /decide
│       └── session_start_routes.py  /de-start
├── portal/
│   └── index.html              Single-page app (no build step)
├── examples/
│   ├── cfo-agent/              Sample: cost intelligence agent
│   └── ops-agent/              Sample: infrastructure monitoring agent
├── render.yaml                 Render.com deploy config (ready to use)
├── requirements.txt            anthropic (only external dependency)
└── start.sh                    Startup script (loads .env, starts server)
```

---

## Requirements

- Python 3.10+
- `anthropic` Python package (`pip install anthropic`)
- Anthropic API key ([get one here](https://console.anthropic.com))
- A place to run Python (see deployment options above)
