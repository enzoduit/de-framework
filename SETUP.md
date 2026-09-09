# SETUP.md — Digital Employees Framework

Complete setup guide for self-hosting on a fresh Ubuntu server (or any Linux VPS).
For cloud deployments (Render, Railway) see `README.md → Deploying the backend`.

---

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| OS | Ubuntu 20.04+ | Any Debian-based Linux works |
| Python | 3.10+ | `python3 --version` |
| Node.js | 18+ | Required only for Cloudflare Pages portal deploy |
| OpenClaw | Any | Required only if DEs use OpenClaw tools |
| Outbound HTTPS | Required | For Anthropic API calls |
| CPU / RAM | 1 vCPU / 512 MB | Each DE session spawns a subprocess |

---

## Step-by-step: Clone → Running

### Step 1 — Clone the repo

```bash
git clone https://github.com/enzoduit/de-framework.git
cd de-framework
```

### Step 2 — Run bootstrap.sh (one-shot setup)

The bootstrap script handles everything: dependencies, directories, systemd service, nginx, and cron.

```bash
sudo bash bootstrap.sh
```

What it does (idempotent — safe to run twice):

| Step | What happens |
|------|-------------|
| System packages | Installs `python3`, `pip`, `nginx`, `cron`, `nodejs` |
| Python deps | `pip install -r requirements.txt` |
| `/var/de-agents/` | Creates the agents directory |
| `/etc/de-framework.env` | Creates env file with **placeholders** (skips if exists) |
| `de-backend.service` | Installs + enables systemd service |
| `/etc/nginx/sites-available/de-api` | Reverse proxy on port 80 → backend 8769 |
| `/etc/cron.d/de-framework-scheduler` | Cron every minute → `/trigger-scheduled` |

### Step 3 — Edit environment variables

```bash
nano /etc/de-framework.env
```

Fill in at minimum:

```env
ANTHROPIC_API_KEY=sk-ant-...         # get at https://console.anthropic.com
DE_API_TOKEN=choose-a-secret-token   # protect the API — use a strong random string
```

Full reference:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `DE_API_TOKEN` | ✅ | — | Bearer token for all API calls |
| `AGENTS_DIR` | — | `/var/de-agents` | Root dir for all DE configs + sessions |
| `DE_MODEL` | — | `claude-haiku-4-5` | Default model (override per-DE in `de.json`) |
| `DE_API_PORT` | — | `8769` | Backend port |
| `OPENCLAW_GATEWAY_URL` | — | — | OpenClaw gateway URL (if using OpenClaw tools) |
| `OPENCLAW_GATEWAY_TOKEN` | — | — | OpenClaw gateway auth token |
| `TELEGRAM_BOT_TOKEN` | — | — | For Telegram notifications from DEs |
| `TELEGRAM_NOTIFY_CHAT_ID` | — | — | Telegram chat ID to notify |
| `DECISIONS_API_URL` | — | — | External webhook for decision notifications |

### Step 4 — Start the service

```bash
systemctl start de-backend
systemctl status de-backend
```

Verify it's up:

```bash
curl http://127.0.0.1:8769/health
# → {"status": "ok", "service": "de-framework"}
```

### Step 5 — Deploy the portal (optional)

The portal is a single HTML file. Deploy to Cloudflare Pages (free):

```bash
# Get your CF token
CF_TOKEN=$(python3 -c "import json; print(json.load(open('path/to/cloudflare-config.json'))['token'])")

# Deploy
npx wrangler pages deploy portal/ \
  --project-name my-de-portal \
  --branch main \
  2>&1
```

Then open the portal URL → ⚙ (settings) → enter:
- **Backend URL**: `http://your-server-ip:8769` (or your domain if nginx + DNS set up)
- **Token**: your `DE_API_TOKEN`

---

## Creating DEs via API

Any agent (or curl command) can create a new DE programmatically using `POST /api/des`.

### Minimal request

```bash
export TOKEN="your-DE_API_TOKEN"

curl -s -X POST http://127.0.0.1:8769/api/des \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "aria",
    "role": "Head of Product",
    "mission": "Define and ship product features. Own the roadmap. Measure with NPS."
  }'
```

Response (201):

```json
{
  "ok": true,
  "de": {
    "name": "aria",
    "display_name": "ARIA",
    "role": "Head of Product",
    "mission": "Define and ship product features...",
    "autonomy_level": 1,
    "tools": ["exec_shell", "read_file", ...],
    "created_at": "2026-09-08T10:00:00+00:00"
  },
  "path": "/var/de-agents/aria"
}
```

### Full request with all fields

```bash
curl -s -X POST http://127.0.0.1:8769/api/des \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "aria",
    "role": "Head of Product",
    "mission": "Define and ship product features. Own the roadmap. Measure with NPS.",
    "autonomy": 1,
    "tools": [
      "exec_shell",
      "read_file",
      "write_file",
      "web_search",
      "ask_colleague",
      "report_to_colleague",
      "request_human_decision"
    ],
    "kpis": [
      {"id": "nps", "name": "NPS Score", "target": 50, "unit": "points", "direction": "up"},
      {"id": "velocity", "name": "Feature velocity", "target": 4, "unit": "features/month", "direction": "up"}
    ],
    "goals": ["Launch v2 by Q4", "Reduce churn by 20%"],
    "responsibilities": {
      "l0": ["Read product metrics", "Summarize customer feedback"],
      "l1": ["Update roadmap", "Write spec docs", "Draft release notes"],
      "l2": ["Kill a feature", "Hire a contractor", "Spend >$500"]
    },
    "hard_constraints": ["Never delete customer data", "Never commit to external deadlines without human approval"],
    "self_evaluation": {
      "schedule": "daily",
      "criteria": ["NPS improved week-over-week", "At least 1 shipped feature per sprint"]
    }
  }'
```

### List all DEs

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8769/api/des
```

### Get one DE

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8769/api/des/aria
```

### Error responses

| Code | Condition |
|------|-----------|
| `400` | `name` missing or contains invalid characters |
| `401` | Missing or wrong Bearer token |
| `409` | DE with that name already exists |
| `500` | Filesystem or unexpected error |

---

## Org chart → DE mapping

When converting a human org chart to Digital Employees, map each role to these fields:

### Field mapping

| Org chart concept | de.json field | Notes |
|-------------------|---------------|-------|
| Job title | `role` | Short, descriptive |
| Name / slug | `name` | lowercase, hyphens only, e.g. `head-of-growth` |
| Department abbreviation | `display_name` | Shown in portal sidebar, e.g. `GROWTH` |
| Job description | `mission` | 1–3 sentences: what this role owns and delivers |
| OKRs / targets | `kpis[]` | Each KPI = name + target + unit + direction |
| Quarterly objectives | `goals[]` | Free-text list |
| "Can do without asking" | `responsibilities.l0` | Autonomous actions, silent |
| "Does it, notifies me" | `responsibilities.l1` | Logged in portal, visible to you |
| "Must ask first" | `responsibilities.l2` | Triggers a decision request — blocks until resolved |
| "Never under any circumstances" | `hard_constraints[]` | Absolute guardrails |
| Reporting frequency | `self_evaluation.schedule` | `manual`, `daily`, `weekly`, `hourly` |
| Seniority / trust level | `autonomy` | 0 = full auto, 1 = log+notify, 2 = always ask |

### Autonomy level guide

| Autonomy | Use for | Example role |
|----------|---------|-------------|
| `0` | Fully trusted, repetitive, low-risk | Monitoring agent (ops), data collector |
| `1` | Default — acts but documents everything | Most operational roles |
| `2` | High-risk, external impact, or money | CFO actions, customer-facing comms |

### Tools by role type

| Role type | Recommended tools |
|-----------|------------------|
| Ops / monitoring | `exec_shell`, `read_file`, `web_search`, `send_telegram`, `request_human_decision` |
| Analyst / reporter | `read_file`, `write_file`, `web_search`, `report_to_colleague` |
| Creative / content | `read_file`, `write_file`, `web_search`, `ask_colleague` |
| Manager / coordinator | `ask_colleague`, `report_to_colleague`, `request_human_decision`, `schedule_next_session` |
| Finance / cost | `read_file`, `web_search`, `request_human_decision`, `send_telegram` |

---

## Example org chart (CEO, CFO, CMO)

### Org chart

```
CEO (Enzo)
├── CFO — Max        → cost intelligence, budget guardrails
├── CMO — Growth     → GEO visibility, content strategy
└── OPS — Ops        → uptime monitoring, self-healing
```

### CFO (Max) — de.json

```json
{
  "name": "max",
  "display_name": "MAX",
  "role": "CFO · Cost Intelligence",
  "color": "#22c55e",
  "autonomy_level": 1,
  "mission": "Monitor all AI and infrastructure spend. Find waste. Enforce budget. Alert on anomalies.",
  "kpis": [
    "Monthly AI cost: stay under $500",
    "Cost per session: track trend",
    "Savings found this month: target >0"
  ],
  "responsibilities": {
    "level_0": [
      "Read cost logs and session data",
      "Calculate cost per session and per DE"
    ],
    "level_1": [
      "Write cost reports to workspace/",
      "Send weekly summary via Telegram"
    ],
    "level_2": [
      "Disable a DE (reduce spend)",
      "Switch models across all DEs",
      "Any action affecting >$100/month"
    ]
  },
  "hard_constraints": [
    "Never access billing credentials directly",
    "Never disable core infrastructure without approval"
  ],
  "tools": ["read_file", "web_search", "send_telegram", "request_human_decision", "write_file"],
  "self_evaluation": {"schedule": "daily"}
}
```

### CMO (Growth) — de.json

```json
{
  "name": "growth",
  "display_name": "GROWTH",
  "role": "Chief Growth Officer · GEO Visibility",
  "color": "#FF4500",
  "autonomy_level": 1,
  "mission": "Drive organic visibility via GEO (Generative Engine Optimization). Own citation count, traffic, and conversion from AI-generated search results.",
  "kpis": [
    "Monthly GEO citations: track trend",
    "Organic sessions from AI sources: track trend",
    "Content quality gate pass rate: >80%"
  ],
  "responsibilities": {
    "level_0": [
      "Read GEO reports and traffic analytics",
      "Research competitor citations"
    ],
    "level_1": [
      "Publish GEO content updates",
      "Update site copy based on research"
    ],
    "level_2": [
      "Launch a new subdomain or site",
      "Purchase any paid promotion",
      "Contact external partners"
    ]
  },
  "hard_constraints": [
    "Never publish content that makes false factual claims",
    "Never contact anyone without human approval"
  ],
  "tools": ["read_file", "write_file", "web_search", "exec_shell", "ask_colleague", "request_human_decision"],
  "self_evaluation": {"schedule": "weekly"}
}
```

### OPS — de.json

```json
{
  "name": "ops",
  "display_name": "OPS",
  "role": "Operations Manager · Uptime",
  "color": "#6366F1",
  "autonomy_level": 1,
  "mission": "Ensure all services, websites, and automated processes are running at all times. Detect outages and self-heal autonomously where possible.",
  "kpis": [
    "Uptime %: target 99.9% for all core services",
    "Mean time to detect: <5 minutes",
    "Auto-remediated incidents: track count",
    "Open incidents: target 0"
  ],
  "responsibilities": {
    "level_0": [
      "Read service status and health endpoints",
      "Read logs and metrics"
    ],
    "level_1": [
      "Restart a crashed service",
      "Clear a full disk",
      "Deploy a hotfix to a static site"
    ],
    "level_2": [
      "Take a core service offline",
      "Roll back a production deployment",
      "Any action affecting >1 hour of downtime"
    ]
  },
  "hard_constraints": [
    "Never delete databases or persistent storage",
    "Never expose credentials in logs"
  ],
  "tools": [
    "exec_shell", "read_file", "write_file",
    "send_telegram", "web_search",
    "schedule_next_session", "ask_colleague",
    "report_to_colleague", "request_human_decision"
  ],
  "self_evaluation": {"schedule": "daily"}
}
```

### Create all three via API

```bash
TOKEN="your-token"
BASE="http://127.0.0.1:8769"

# CFO
curl -s -X POST $BASE/api/des \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"max","role":"CFO · Cost Intelligence","mission":"Monitor all AI and infrastructure spend. Find waste. Enforce budget.","autonomy":1}'

# CMO
curl -s -X POST $BASE/api/des \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"growth","role":"Chief Growth Officer · GEO Visibility","mission":"Drive organic visibility via GEO. Own citation count and traffic.","autonomy":1}'

# OPS
curl -s -X POST $BASE/api/des \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ops","role":"Operations Manager · Uptime","mission":"Ensure all services are running. Detect outages and self-heal.","autonomy":1}'
```

---

## Adding Custom Tools

Custom tools let you expose any shell script or Python script as a callable tool that appears in the Tool Library and can be enabled for any DE.

Tool definitions live in `/var/de-framework-tools/` — one JSON file per tool.

### Option A — Drop a JSON file directly

1. Copy your script to an accessible path:
   ```bash
   cp /my/scripts/meta_report.sh /home/user/scripts/meta_report.sh
   chmod +x /home/user/scripts/meta_report.sh
   ```

2. Create a definition file:
   ```bash
   cat > /var/de-framework-tools/meta_performance.json << 'EOF'
   {
     "id": "meta_performance",
     "name": "meta_performance",
     "description": "Run the Meta Ads performance daily report",
     "icon": "📊",
     "script": "/home/user/scripts/meta_report.sh",
     "args_schema": {
       "type": "object",
       "properties": {
         "date": {"type": "string", "description": "Date to run for (YYYY-MM-DD), defaults to yesterday"}
       }
     }
   }
   EOF
   ```

3. Click **🔄 Rediscover** in the portal Tool Library — your tool appears instantly.

4. Open any DE profile → Tools → **+ Add** to enable it.

### Option B — POST /api/tools/register

```bash
curl -s -X POST http://127.0.0.1:8769/api/tools/register \
  -H "Authorization: Bearer $DE_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "meta_performance",
    "name": "meta_performance",
    "description": "Run Meta Ads performance daily report",
    "icon": "📊",
    "script": "/home/user/scripts/meta_report.sh",
    "args_schema": {}
  }'
```

Response: `{"ok": true, "tool": {..., "source": "custom"}}`

Error codes: `400` missing fields, `409` tool ID already exists.

### Tool definition fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | ✅ | Unique identifier (alphanumeric + `_` `-`; starts with a letter) |
| `name` | ✅ | Display name (usually same as `id`) |
| `description` | ✅ | Shown to DEs — describe what the tool does and when to call it |
| `script` | ✅ | Absolute path to the executable (`/usr/bin/python3`, `/bin/bash`, etc.) |
| `icon` | no | Emoji icon shown in Tool Library (default 🔧) |
| `script_args` | no | Static argv appended after the script path (e.g. `["-c", "..."]`) |
| `args_schema` | no | JSON Schema for per-call arguments; passed as `ARG_<KEY>=value` env vars |

### How arguments reach your script

When a DE calls a custom tool with arguments (e.g. `{"date": "2026-09-01"}`), the DE Framework:
1. Runs `[script] + script_args` as a subprocess
2. Exports each input field as an environment variable: `ARG_DATE=2026-09-01`

Your script reads them like any env var:
```bash
#!/bin/bash
DATE=${ARG_DATE:-$(date -d yesterday +%Y-%m-%d)}
echo "Running report for $DATE"
```

or in Python:
```python
import os
date = os.environ.get('ARG_DATE') or 'yesterday'
```

### Removing a custom tool

```bash
rm /var/de-framework-tools/meta_performance.json
# Then click Rediscover in portal to clear it from the Tool Library
```

Note: removing the definition file does not remove the tool from any DE's `de.json` tools list. Edit DE profiles manually via PATCH `/de/<name>/tools` if needed.

---

## Troubleshooting

### Backend not starting

```bash
# Check service status
systemctl status de-backend

# View logs
tail -50 /tmp/de-backend.log

# Check env file is loaded correctly
grep -v '^#' /etc/de-framework.env | grep -v '^$'

# Test manually
cd /root/.openclaw/workspace/de-framework
source /etc/de-framework.env
python3 backend/server.py
```

### 401 on all API calls

- Check `DE_API_TOKEN` in `/etc/de-framework.env` matches what you're sending
- Confirm you're using `Authorization: Bearer <token>` (not `Basic`, not bare token)

### nginx 502

- Backend not running: `systemctl start de-backend`
- Wrong port: check `DE_API_PORT` in env matches nginx proxy_pass port
- `nginx -t` to verify nginx config syntax

### Cron not triggering

```bash
# Check cron file exists
cat /etc/cron.d/de-framework-scheduler

# Check cron service running
systemctl status cron

# Test manually
curl -s http://127.0.0.1:8769/trigger-scheduled
```

---

## Credential Management

Custom tool scripts can require API keys without storing them in plaintext. The framework encrypts all credentials at rest using **AES-256 (Fernet)** with a key derived from `DE_API_TOKEN` via PBKDF2 — no separate key file needed.

### How it works

1. **Declare credentials in your tool JSON** — add `required_credentials` to the tool definition:

```json
{
  "id": "meta_performance",
  "name": "Meta Performance Reporter",
  "description": "Pulls Meta Ads performance data",
  "script": "/var/de-framework-tools/meta_performance.sh",
  "required_credentials": ["META_API_KEY", "META_AD_ACCOUNT_ID"]
}
```

2. **Set credentials** — via portal (Tool Library → click ⚠ missing) or API:

```bash
# Via API
source /etc/de-framework.env
curl -s -X POST \
  -H "Authorization: Bearer $DE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"META_API_KEY","value":"your-key","description":"Meta Ads API Key"}' \
  http://127.0.0.1:8769/api/credentials
```

3. **Runtime injection** — when a DE runs the tool, credentials are decrypted and passed as environment variables to the script. They are **never logged, never stored in session files, never appear in plaintext**.

```bash
# Inside your script, use them as normal env vars:
echo "Running with account: $META_AD_ACCOUNT_ID"
curl -H "Authorization: Bearer $META_API_KEY" ...
```

4. **Portal credential status** — the Tool Library shows ✅ set or ⚠ missing for each credential. Click ⚠ to set inline.

### API Reference

```bash
# List all credentials (metadata only — values never returned)
curl -H "Authorization: Bearer $DE_API_TOKEN" http://127.0.0.1:8769/api/credentials

# Store a credential
curl -X POST -H "Authorization: Bearer $DE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"SOME_KEY","value":"secret123","description":"Optional description"}' \
  http://127.0.0.1:8769/api/credentials

# Delete a credential
curl -X DELETE -H "Authorization: Bearer $DE_API_TOKEN" \
  http://127.0.0.1:8769/api/credentials/SOME_KEY
```

### Security notes

- **Encryption**: AES-256 via Python `cryptography` Fernet. Key = PBKDF2(DE_API_TOKEN, salt=`de-framework-creds`, 100,000 iterations).
- **Storage**: `/var/de-framework-credentials/{ID}.enc` — one file per credential, binary. Metadata index (`index.json`) never stores values.
- **Runtime**: decrypted in-memory only, passed as subprocess env vars. Not stored in session JSON, logs, or anywhere else.
- **Rotation**: changing `DE_API_TOKEN` invalidates all existing `.enc` files (they can no longer be decrypted). Re-set credentials after token rotation.
- **Dependency**: `pip install cryptography` — already in `requirements.txt`.

---

## File layout after setup

```
/var/de-agents/                 ← AGENTS_DIR
  aria/
    de.json                     ← DE profile + config
    job.md                      ← Mission brief (system prompt)
    memory.md                   ← Persistent long-term memory
    metrics.json                ← KPI snapshots
    decisions.json              ← Approval queue
    schedule.json               ← Scheduled activities
    sessions/                   ← One JSON per run
      ws-aria-20260908-*.json
    workspace/                  ← DE's working files

/etc/de-framework.env           ← Environment variables (secrets here)
/etc/systemd/system/de-backend.service
/etc/nginx/sites-available/de-api
/etc/cron.d/de-framework-scheduler
/tmp/de-backend.log             ← Backend logs

/var/de-framework-credentials/  ← Encrypted credential store
  index.json                    ← Metadata (no values)
  META_API_KEY.enc              ← AES-256 Fernet encrypted value
  META_AD_ACCOUNT_ID.enc

/var/de-framework-tools/        ← Custom tool definitions
  meta_performance.json         ← Tool JSON (includes required_credentials)
```
