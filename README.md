# Digital Employees Framework

Run autonomous AI agents ("Digital Employees") with defined missions, KPIs, and approval gates — powered by Claude via the Anthropic API.

Each Digital Employee has a **mission**, knows what it can do **autonomously**, what it should **document**, and what it must **ask you first**. It runs on a schedule or on demand, logs every step, and pauses for human decisions when it hits something risky.

## What you get

- **Split-screen portal** — list of employees on the left, Chat / Progress / Profile on the right
- **Chat interface** — message any employee and watch it work in real time
- **Create DE wizard** — define mission, KPIs, autonomy levels, self-evaluation, and research queries through a 5-step form. The agent's `job.md` is generated automatically.
- **Autoresearch** — agents can proactively research topics and update their own knowledge base
- **Decision queue** — agents pause and ask for approval on risky actions; you approve/reject in the portal or via API
- **Session replay** — every agent run is logged step by step (trigger → reasoning → action → result → complete)

## Architecture

```
de-framework/
  backend/          Python REST API (stdlib only, no dependencies except anthropic)
    server.py       Entry point — runs on DE_API_PORT (default 8766)
    config.py       All config from environment variables
    core/
      react_engine.py     ReAct loop (Observe → Reason → Act)
      session_runner.py   Spawns the ReAct engine for each session
      work_session.py     Persistent session file manager
    routes/
      de_routes.py        /de-list, /de/<name>, /de/create, ...
      decisions_routes.py /decisions, /decide
      session_start_routes.py  /de-start, /de/<name>/sessions/start

  portal/           Web UI — deploy to Cloudflare Pages (or serve statically)
    index.html      Single-page split-screen app
    functions/      Cloudflare Pages Functions (proxy to backend API)
    _routes.json    Route config

  examples/
    cfo-agent/      Sample: cost monitoring agent
    ops-agent/      Sample: infrastructure monitoring agent
```

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/enzoduit/de-framework.git
cd de-framework
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY, DE_API_TOKEN, AGENTS_DIR
```

### 2. Start the backend

```bash
pip install anthropic
source .env
python backend/server.py
# Running on port 8766
```

### 3. Open the portal

Open `portal/index.html` in a browser **or** deploy to Cloudflare Pages (see below).

For local development, point the CF functions' `UPSTREAM_URL` to `http://localhost:8766` or use a tunnel (ngrok, Cloudflare Tunnel).

### 4. Create your first Digital Employee

Click **+ NEW** in the sidebar and fill in the 5-step wizard:

| Step | What you define |
|------|----------------|
| Identity | Slug name, display name, role, color |
| Mission | What this agent owns + KPIs |
| Autonomy | Level 0 / 1 / 2 actions + hard constraints |
| Evaluation | Success criteria, run schedule, data sources |
| Research | Optional autoresearch queries + frequency |

The framework generates `de.json` (profile) and `job.md` (full mission brief) automatically.

## Creating a Digital Employee manually

If you prefer files over the wizard:

**`agents/my-agent/de.json`**
```json
{
  "name": "my-agent",
  "display_name": "MY AGENT",
  "role": "What this agent does",
  "color": "#FF4500",
  "mission": "One sentence mission statement.",
  "kpis": ["KPI 1", "KPI 2"],
  "responsibilities": {
    "level_0": ["Things it does autonomously"],
    "level_1": ["Things it does and documents"],
    "level_2": ["Things that require your approval"]
  },
  "hard_constraints": ["Things it must never do"],
  "data_sources": ["http://localhost:3002/api/summary"],
  "self_evaluation": {
    "criteria": ["Success looks like X"],
    "schedule": "daily"
  },
  "autoresearch": {
    "enabled": false,
    "queries": [],
    "schedule": "daily"
  },
  "triggers": [
    {"type": "cron", "schedule": "Daily 08:00 UTC", "description": "Scheduled run"},
    {"type": "user", "description": "On-demand via portal"}
  ]
}
```

**`agents/my-agent/job.md`** — plain markdown mission brief. The ReAct engine reads this as the agent's system prompt. Write it like a job description: mission, KPIs, what the agent can do at each autonomy level, data sources, and success criteria.

## Autonomy levels

Every agent's `job.md` defines three levels that control when the ReAct loop pauses:

| Level | Behavior | Example |
|-------|----------|---------|
| **0** | Acts immediately, no notification | Read metrics, ping services, write logs |
| **1** | Acts, then documents in portal | Deploy a page, update a config file |
| **2** | Pauses and requests human decision | Disable a cron job, send external comms |

When a Level 2 situation is hit, the agent calls `request_human_decision` → the session pauses → the decision appears in the portal's Decisions panel → you approve or reject → the session resumes automatically.

## Autoresearch

When `autoresearch.enabled = true`, the agent's `job.md` includes instructions to:

1. Search for each query using `http_get` on available sources
2. Summarize findings
3. Append key insights to `memory.md`
4. Update `metrics.json` with any relevant metrics found

Schedule autoresearch runs via cron the same way you schedule regular runs.

## Chat interface

The portal's **Chat** tab lets you message any employee directly:

1. Type a message → triggers a new session with `trigger_type: chat`
2. The ReAct loop runs and you see each step in real time
3. When the session completes, the final summary appears as the agent's reply
4. If the agent needs a decision, it pauses and shows a banner

## Portal deployment (Cloudflare Pages)

```bash
# Deploy the portal
npx wrangler pages deploy portal/ --project-name my-de-portal

# Set secrets in Cloudflare dashboard → Pages → Settings → Environment Variables:
#   DE_API_TOKEN = your DE_API_TOKEN
#   DE_API_URL   = https://your-backend-url.com
```

The `portal/functions/` directory contains CF Pages Functions that proxy every API call to your backend. Update `UPSTREAM_URL` in each function or set `DE_API_URL` as a Pages secret.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key for the ReAct engine |
| `DE_API_TOKEN` | ✅ | — | Auth token for the backend API |
| `AGENTS_DIR` | ✅ | `./agents` | Root directory containing all DE agent folders |
| `DE_MODEL` | — | `claude-haiku-4-5` | Model for all DE sessions (per-agent override via `de.json` → `"model"`) |
| `DE_MAX_ITERATIONS` | — | `8` | Default ReAct loop iterations (per-agent override via `de.json` → `"max_iterations"`) |
| `DE_API_PORT` | — | `8766` | Backend API port |
| `DECISIONS_API_URL` | — | — | URL for human-in-loop decision notifications (optional) |
| `TELEGRAM_BOT_TOKEN` | — | — | For Telegram notifications |
| `TELEGRAM_NOTIFY_CHAT_ID` | — | — | Telegram chat ID for notifications |
| `ELEVENLABS_AGENT_ID` | — | — | ElevenLabs voice agent ID (optional) |
| `ELEVENLABS_API_KEY` | — | — | ElevenLabs API key (optional) |

## Session flow

```
User/cron triggers session
  └─ session_runner.py creates WorkSession (sessions/<id>.json)
      └─ ReActEngine.run() starts the loop
          ├─ OBSERVE  read current state (metrics.json, memory.md, log.jsonl)
          ├─ REASON   Claude chooses next action
          ├─ ACT      execute tool (read_file, exec_command, http_get, ...)
          ├─ OBSERVE  tool result back into context
          └─ REPEAT   until done, decision needed, or max_iterations
              └─ if request_human_decision called:
                  ├─ session.status = "paused_human"
                  ├─ decision written to decisions.json + portal-inbox.jsonl
                  └─ human approves/rejects → session resumes via /de-start --resume
```

## Extending

**Add a tool:** Pass any `fn`-bearing tool definition to `ReActEngine(tools=[...])` in `session_runner.py`. The tool receives `input_data: dict` and returns a string.

**Add a colleague:** Set `"colleagues": ["other-agent"]` in `de.json`. The agent can then call `ask_colleague` to drop a message in another agent's `inbox.jsonl`.

**Custom session runner:** Implement your own runner that creates a `WorkSession`, calls `session.add_step()`, and calls `session.set_status()`. The portal, API, and decisions system work unchanged.

## Requirements

- Python 3.10+
- `anthropic` pip package
- Cloudflare account (for portal hosting, optional)
- Anthropic API key
