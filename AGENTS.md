# AGENTS.md — Guide for AI Agents Working in This Repo

This file is for you — an AI agent tasked with extending, debugging, or deploying the DE Framework. Read this before touching any code.

---

## What this repo is

A backend + portal for running autonomous AI agents ("Digital Employees") with:
- Defined missions, KPIs, and autonomy levels
- A ReAct loop engine (Claude-powered)
- Human-in-the-loop via structured output types (Decision / Document / Insight)
- Session persistence (every run → a JSON file, append-only)

The human is not a reviewer of every step — they're a manager whose **attention is a scarce resource**. Everything is built to maximize the quality of what reaches them, not the quantity.

---

## Architecture

```
Portal (static HTML)
        │  HTTP + Bearer token
        ▼
Backend API (Python, default port 8766)
        │
        ├── ReActEngine  ← runs Claude in a loop (think → act → observe → repeat)
        ├── WorkSession  ← writes every step to sessions/{id}.json
        └── AGENTS_DIR   ← file system, one folder per DE
              ├── {name}/de.json          ← identity + config
              ├── {name}/job.md           ← system prompt (the DE's "brain")
              ├── {name}/memory.md        ← persistent memory across sessions
              ├── {name}/metrics.json     ← KPI snapshots
              ├── {name}/decisions.json   ← pending Level-2 decisions
              ├── {name}/inbox.jsonl      ← messages from colleague DEs
              └── {name}/sessions/        ← one JSON per run
```

**Default port:** 8766 (env: `DE_API_PORT`)

---

## Files to read before touching anything

| File | Role |
|---|---|
| `backend/server.py` | HTTP router (maps paths to handlers) |
| `backend/core/react_engine.py` | ReAct loop + tool execution |
| `backend/core/session_runner.py` | Spawns ReAct engine per trigger |
| `backend/core/work_session.py` | Session file manager (read/write steps) |
| `backend/routes/de_routes.py` | Main API routes + TOOL_LIBRARY metadata |
| `backend/core/tool_implementations.py` | Executable tool functions |
| `backend/core/tool_discovery.py` | Tool list served to portal (cached) |

Read all 4 backend files before any change: `tool_discovery.py`, `tool_implementations.py`, `de_routes.py`, `server.py`.

---

## Known failure modes — read these before you break things

### 1. Tool schema error breaks ALL DEs silently

**Symptom:** Every DE crashes at iteration 1 with `llm_error`  
**Cause:** A tool in `tool_implementations.py` has a field Anthropic rejects  
**Allowed fields only:** `name`, `description`, `input_schema`, `cache_control`  
**Diagnosis:** Check `/tmp/session-{de_name}-{session_id}.log` for real Anthropic error  
**Fix:** Remove stray fields (e.g. `'source': 'builtin'`), then restart backend

This breaks ALL DEs simultaneously since they share `get_tool_defs()`. If everything breaks at once, this is the culprit.

---

### 2. session_runner must use ReActEngine + WorkSession

**Symptom:** Portal shows sessions but timeline has no steps  
**Cause:** Using `chatCompletions` routing — saves a single `type: "openclaw_response"` step the portal ignores  
**Fix:** Use `ReActEngine` + `WorkSession.add_step()`. Only these step types are rendered:  
`trigger`, `reasoning`, `action`, `observation`, `decision_request`, `decision_response`, `complete`, `colleague_request`

---

### 3. max_tokens too low → API 400

**Symptom:** ReAct loop crashes mid-run with "messages must end with a user message"  
**Cause:** `max_tokens=1024` → `stop_reason="max_tokens"` on text response → loop continues → next call has no user message  
**Fix (both required):**
1. Use `max_tokens=4096`
2. Break condition: `stop_reason in ("end_turn", "max_tokens") and not tool_calls_made`

---

### 4. DE_API_TOKEN extraction

**Wrong:** `source /etc/de-framework.env` does NOT expose `$DE_API_TOKEN` as a shell variable  
**Right:**
```bash
TOKEN=$(grep '^DE_API_TOKEN=' /etc/de-framework.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8766/de-list
```

---

### 5. Always compile + restart after backend changes

```bash
cd /path/to/de-framework
python3 -m py_compile \
  backend/core/tool_discovery.py \
  backend/core/tool_implementations.py \
  backend/routes/de_routes.py \
  backend/server.py
systemctl restart de-backend && sleep 2 && systemctl is-active de-backend
```

Never assume a change is live without restarting. Syntax errors will silently fail if you skip the compile step.

---

### 6. Caddy routing order (production deployments with Caddy)

`/dev*` handler MUST appear before `/de*` in Caddyfile — otherwise `/dev` matches on the DE Framework route.

Caddy v2.11.2 has a redirect bug: `Location` header gets set to `"302"` instead of the URL. Use your app server for root redirects, not Caddy `redir`.

Use `handle` not `handle_path` — `handle_path` strips the prefix, which breaks `/dev` → landing as `/`.

Token in query string can arrive as an array when Caddy duplicates it. Always handle `query.t` as potentially `string | string[]`.

---

## Adding a tool

1. Add metadata to `TOOL_LIBRARY` in `backend/routes/de_routes.py`:
```python
{"id": "my_tool", "name": "my_tool", "description": "What it does", "icon": "🔧"}
```

2. Add implementation in `backend/core/tool_implementations.py` inside `get_tool_defs()`:
```python
{
    "name": "my_tool",
    "description": "What it does",
    "input_schema": {
        "type": "object",
        "properties": {"param": {"type": "string"}},
        "required": ["param"]
    },
    "fn": lambda input_data: {"result": my_impl(input_data["param"])}
}
```
**Only allowed fields:** `name`, `description`, `input_schema`, `fn`, `cache_control`. Any other field breaks all DEs.

3. Compile + restart (see above). Tool appears in portal automatically — no frontend changes needed.

---

## Custom tools (drop-in, no restart needed)

Drop a JSON file in `$CUSTOM_TOOLS_DIR` (default: `/var/de-framework-tools/`):
```json
{
  "id": "my_tool",
  "name": "my_tool",
  "description": "What it does",
  "script": "/path/to/script.sh",
  "icon": "🔧"
}
```
Loaded fresh on every tool discovery call. Portal shows them with 🔧 CUSTOM badge.

---

## Session invariants

- **Append-only.** Never modify or delete past sessions.
- **Session ID format:** `ws-{de_name}-{YYYYMMDD-HHMMSS}-{6char_hex}`
- Every session lives in `{AGENTS_DIR}/{de_name}/sessions/{id}.json`
- Status values: `running`, `complete`, `error`, `paused_human`

---

## Debugging a broken DE

1. Trigger a session manually:
   ```bash
   curl -s -X POST http://127.0.0.1:8766/de-start \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"de_name": "my-agent", "trigger_type": "user"}'
   ```
2. Find the session file in `{AGENTS_DIR}/my-agent/sessions/` — latest `.json`
3. Check the log: `/tmp/session-my-agent-{session_id}.log` for the real error
4. **All DEs broken at once** → tool schema error (see §1 above)
5. **Portal shows no steps** → ReActEngine routing issue (see §2 above)
6. **Session stuck at `paused_human`** → resolve via `POST /decide` with `decision_id`

---

## Hosting recommendation

**Demo / development:** Run locally or Render.com (free tier).  
> ⚠️ Render free tier = ephemeral storage. Agents lose all memory on redeploy. Not suitable for production.

**Production (recommended):** Ubuntu 22.04 LTS VPS + systemd + Caddy

- `bootstrap.sh` handles full setup (idempotent, safe to re-run)
- `deploy/de-framework.service` → systemd ensures auto-restart on crash
- Caddy handles HTTPS + routing
- Persistent disk = agents keep memory across deploys and restarts

```bash
# Production setup
git clone https://github.com/enzoduit/de-framework.git
cd de-framework
bash bootstrap.sh
```

Minimal Caddy config for HTTPS:
```caddyfile
your-domain.com {
    handle /de* {
        reverse_proxy localhost:8766
    }
}
```

**Container deployments:** Set `CUSTOM_TOOLS_DIR` to a persistent volume path — the default `/var/de-framework-tools` won't survive container restarts.

---

## What NOT to do

- Do not use `chatCompletions` routing for DE sessions — use `ReActEngine`
- Do not add extra fields to tool definitions — only `name`, `description`, `input_schema`, `fn`, `cache_control`
- Do not modify or delete session files in `sessions/` — they are an audit log
- Do not hardcode the port — always use `DE_API_PORT` env var
- Do not assume backend changes are live — always compile + restart
