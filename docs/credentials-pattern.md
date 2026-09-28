# Credentials Pattern — DE Framework

## Rule: No Hardcoded Credentials

All credentials MUST be read from environment variables or server-side config files — never hardcoded in job.md, pre_fetch.py, or any file committed to a public repo.

---

## Credential Sources (Priority Order)

| Source | Where | Used for |
|---|---|---|
| `/etc/de-framework.env` | Server, auto-loaded by session_runner.py | All DEs |
| `workspace/cloudflare-config.json` | Per-DE workspace, server-side only | Deploy tokens |
| `~/.git-credentials` | Git credential store | All `git push` operations (automatic) |
| OpenClaw secrets store | Operator-managed | One-off credentials |

---

## GitHub Token

### Canonical access pattern for DE scripts:

```python
import os, subprocess
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN') or subprocess.check_output(
    ["grep", "GITHUB_TOKEN", "/etc/de-framework.env"],
    text=True
).split('=', 1)[1].strip().strip('"')
```

### For shell scripts:

```bash
GITHUB_TOKEN="${GITHUB_TOKEN:-$(grep GITHUB_TOKEN /etc/de-framework.env | cut -d= -f2 | tr -d '\"')}"
```

### For git push (no token needed):
Git uses `~/.git-credentials` via the `store` credential helper automatically.
No explicit token needed for `git push` or `git clone` from a DE script.

---

## Deploy Config (grow_* agents)

GEO growth agents that deploy to Cloudflare Pages use a `cloudflare-config.json` in their workspace.
This file is **server-side only** — never committed to GitHub.

```json
{
  "github_token": "<ghp_...>",
  "cloudflare_token": "<CF_API_TOKEN>",
  "account_id": "<CF_ACCOUNT_ID>",
  "pages_project": "<project-name>"
}
```

Reading the config in a DE script:

```python
import json
from pathlib import Path

DE_NAME = Path(__file__).parent.parent.name
WORKSPACE = Path('/var/de-agents') / DE_NAME / 'workspace'
config = json.loads((WORKSPACE / 'cloudflare-config.json').read_text())
GITHUB_TOKEN = config['github_token']
CF_TOKEN = config['cloudflare_token']
```

If `cloudflare-config.json` is missing → log one line → STOP. Do NOT search for alternative paths.

---

## Perplexity API Key

Stored per-DE in `job.md` under the Credentials section OR in `workspace/cloudflare-config.json`.
Access pattern:

```python
import os
PPLX_KEY = os.environ.get('PERPLEXITY_API_KEY') or config.get('perplexity_key', '')
```

---

## Security Rules

1. **NEVER** hardcode tokens in `job.md` (use them from env/config, not inline)
2. **NEVER** pass tokens as CLI arguments (they appear in `ps aux` output)
3. **NEVER** commit cloudflare-config.json or any file containing real tokens to a git repo
4. **NEVER** log token values — log "token loaded" or "token missing", not the value
5. **NEVER** search for credentials mid-session: if the config file is missing → STOP

---

## Token Storage for New DEs

When onboarding a new DE that deploys content:

1. Create `/var/de-agents/<name>/workspace/cloudflare-config.json` (from the operator terminal)
2. Verify with `python3 -c "import json; d=json.load(open('cloudflare-config.json')); print(list(d.keys()))"`
3. Add `cloudflare-config.json` to the DE's workspace `.gitignore`

The session_runner.py exposes `/etc/de-framework.env` contents as environment variables for every session,
so `GITHUB_TOKEN` and other framework-level credentials are always available without explicit file reading.
