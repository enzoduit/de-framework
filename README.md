# Digital Employees Framework for OpenClaw

Run autonomous AI agents ("Digital Employees") with a structured job definition, persistent work sessions, a decision queue for human approval, and a portal UI — all powered by [OpenClaw](https://openclaw.ai).

## What is a Digital Employee?

A Digital Employee (DE) is an autonomous agent that:
- Has a **mission and job description** (`job.md`) defining what it does, what it can do autonomously, and what needs human approval
- Runs **work sessions** — each session is logged step-by-step (trigger → reasoning → action → result)
- Creates **decisions** when it hits something that requires human approval
- Appears in the **portal UI** where you can monitor sessions, approve decisions, and start new sessions manually

## Components

```
backend/          REST API server (Python, stdlib only)
  server.py       Entry point
  config.py       All config from environment variables
  routes/         API route handlers (decisions, DE management, workspace, tasks)
  core/           OpenClaw-specific engine (react_engine, session_runner, work_session)

portal/           Web UI (Cloudflare Pages)
  index.html      Single-page portal
  js/             Extracted JS modules (de-tab, decisions-tab)
  functions/      Cloudflare Pages Functions (proxy to backend API)

examples/         Sample DE configurations
  cfo-agent/      Example: Cost monitoring agent
  ops-agent/      Example: Infrastructure monitoring agent
```

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env with your values
```

### 2. Create your agent directory

```bash
mkdir -p agents/my-agent/sessions agents/my-agent/workspace
cp examples/cfo-agent/de.json agents/my-agent/de.json
cp examples/cfo-agent/job.md agents/my-agent/job.md
# Edit de.json and job.md for your agent
```

### 3. Start the backend API

```bash
pip install -r requirements.txt
python backend/server.py
# Runs on port 8766 by default (set DE_API_PORT in .env to change)
```

### 4. Deploy the portal

```bash
# Deploy to Cloudflare Pages
npx wrangler pages deploy portal/ --project-name my-de-portal
```

The portal talks to your backend via the Cloudflare Functions (configured in `portal/functions/`). Update the `UPSTREAM_URL` in each function to point to your backend (via a tunnel or public URL).

## Creating a Digital Employee

### `de.json` — Agent profile

```json
{
  "name": "my-agent",
  "display_name": "MY AGENT",
  "role": "Role Description",
  "color": "#FF4500",
  "mission": "One sentence mission.",
  "kpis": ["KPI 1", "KPI 2"],
  "responsibilities": {
    "level_0": ["Things it does autonomously, no approval needed"],
    "level_1": ["Things it does and documents (you can revert)"],
    "level_2": ["Things that require your explicit approval"]
  },
  "data_sources": ["http://localhost:3002/api/summary"],
  "triggers": [
    {"type": "cron", "schedule": "Daily 08:00", "description": "Daily check"}
  ],
  "colleagues": ["other-agent-name"]
}
```

### `job.md` — Full mission brief

Plain markdown. Write it like a job description — mission, KPIs, what the agent can do at each autonomy level, data sources, decision quality standards. The session runner passes this entire file as the mission to the LLM.

## Starting Sessions

**Via portal:** AGENTS tab → click an agent → ▶ START

**Via API:**
```bash
curl -X POST http://localhost:8766/de/my-agent/sessions/start \
  -H "Authorization: Bearer $DE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"user","trigger_context":"Your task description here"}'
```

## Session Visualization

Every session is logged step-by-step in `agents/<name>/sessions/<id>.json`:

- `trigger` — what started the session
- `reasoning` — LLM thinking steps
- `action` — tool calls (exec_command, read_file, http_get, etc.)
- `observation` — tool results
- `decision_request` — when the agent pauses for human approval
- `decision_response` — once you approve/reject in the portal
- `complete` — session summary

The portal shows all steps in real-time while a session is running (🔴 LIVE indicator).

## Decision Flow

1. Agent hits a Level 2 action → calls `request_human_decision` tool
2. Decision appears in the portal's DECISIONS tab
3. You approve/reject (optionally add a note)
4. If approved: session resumes automatically with your response injected
5. Agent continues from where it paused

## Architecture Notes

**OpenClaw-specific parts:**
- `core/react_engine.py` — The ReAct (Reason-Act) loop using the Anthropic API via OpenClaw
- `core/session_runner.py` — Spawns react_engine for each session, provides standard tools
- Session triggering via OpenClaw cron system

**Provider-agnostic parts:**
- `core/work_session.py` — Session file management (JSON files, no OpenClaw dependency)
- `backend/routes/` — REST API layer
- `portal/` — Web UI
- `de.json` / `job.md` format

To adapt for other LLM runtimes: implement your own runner that creates a `WorkSession`, logs steps via `session.add_step()`, and calls `session.set_status()`. The rest (portal, API, decisions) works unchanged.

## Requirements

- Python 3.10+
- OpenClaw (for the core agent runner)
- Cloudflare account (for portal hosting via Pages)
- Anthropic API key (via OpenClaw config)
