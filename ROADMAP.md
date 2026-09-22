# DE Framework — Roadmap

Feedback and open items from real-world deployments. Prioritized for highest leverage first.

---

## P1 — High impact (current gap costs significant custom build work)

### 1. Workspace File Server (built-in)

**Gap:** No built-in HTTP server to serve `workspace/pages/` with token auth.

**Impact:** Every deployment that needs a custom portal must build a complete HTTP server from scratch. One production deployment resulted in ~3,000 lines of custom Node.js (token auth system, project management, file upload/serving, dashboard serving, branding API, known-users tracking) — all to solve what is essentially "serve this folder over HTTP with a bearer token."

**What it would look like:**
- Serve `{AGENTS_DIR}/../pages/` (or configurable) at a path like `/pages/`
- Bearer token auth (same `DE_API_TOKEN`)
- MIME type detection
- Optional: upload endpoint

---

### 2. Output Type System (Decision / Document / Insight)

**Gap:** No built-in concept of output types with type-appropriate human-response options.

**Impact:** Every deployment re-invents the pattern of "when does the human need to be involved and how." The current `request_human_decision` is useful but only covers one type (blocking decisions). Documents and Insights have no native representation.

**What it would look like:**

| Type | Agent waiting? | Human response options |
|------|---------------|----------------------|
| 🔔 Decision | Yes | Continue / Feedback+Continue / Stop |
| 📄 Document | No | Useful / Could be better (free text) |
| 📊 Insight | No | Seen / What do I do with this? |

Feedback on Documents gets written to `memory.md` automatically. Insights appear as notifications, not blocking modals.

**Why this matters:** Binary Approve/Reject is the wrong mental model for AI work. "Approve" implies exact authorization; "Reject" implies "never do this." Neither captures the nuance of "yes, but focus on long-term donors." Free-text responses that go back into the session are the right pattern.

---

### 3. Session-Reader API (human-readable step labels)

**Gap:** No official API to render JSONL session steps for non-technical users.

**Impact:** Session steps show raw tool names (`meta.get_campaigns`, `exec_shell`) which mean nothing to a fundraising coordinator. Every deployment builds a custom rendering layer.

**What it would look like:**
- `GET /de/{name}/sessions/{id}/readable` — returns steps with human labels
- Tool-name mapping table (configurable per deployment)
- Built-in defaults for common tools

**Example:**
```
exec_shell → 🖥️ Ran system command
web_search → 🌐 Searched the web
write_file → 📝 Saved a file
read_file  → 📖 Read a file
send_telegram → 📨 Sent notification
```

---

## P2 — Medium impact

### 4. Post-Restart Hook

**Gap:** No built-in mechanism to run initialization logic after the backend restarts.

**Impact:** Deployments that need to verify state after restart (check running sessions, resume paused sessions, send a Telegram notification) must implement manual startup scripts and document them in `bootstrap.sh`.

**What it would look like:** A configurable `post_restart_hook` in env or config — a shell command or Python function that runs once the server is healthy.

---

### 5. Workspace Git Tracking (default on)

**Gap:** `AGENTS_DIR` is not tracked by git by default. Important documents (`REQUIREMENTS.md`, `memory.md`, `job.md`) can be lost during cleanup or migration with no recovery path.

**Impact:** Real production deployments have lost configuration documents with no recovery. Session files are more recoverable (JSON, sequential) but memory and job definitions are not.

**What it would look like:** `bootstrap.sh` initializes a git repo in `AGENTS_DIR` and commits on every write to `de.json`, `job.md`, `memory.md`, `metrics.json`. Diffs are human-readable and meaningful.

---

### 6. Caddy Configuration Template

**Gap:** No reference Caddyfile for typical DE Framework setups.

**Impact:** Common Caddy mistakes (routing order, `handle` vs `handle_path`, redirect bugs in v2.11.2, token duplication) cost hours of debugging per deployment. See `AGENTS.md` for the documented bugs.

**What it would look like:** A `deploy/Caddyfile.example` with annotations:
- Token auth
- Cloudflare Access header passthrough
- `/de*` routing (with `/dev*` caveat — must come first)
- HTTPS termination
- Portal static serving

---

## P3 — Nice to have

### 7. Decision Primitive (built-in pause/resume)

**Gap:** `request_human_decision` creates a decision record but the resume mechanism requires external polling (`/decide` endpoint + session restart).

**What it would look like:** A native concept where a session can suspend itself, wait for a structured human response, and resume — without requiring the operator to wire up a polling/webhook system.

---

### 8. Bonjour/mDNS Permanent Disable

**Gap:** Bonjour re-enables itself on macOS/Docker image changes. No permanent disable mechanism via config.

**Impact:** Minor but recurrent — causes unexpected network behavior in containerized deployments. Should be configurable via env var: `DISABLE_BONJOUR=true`.

---

## Open implementation items (from ACNUR deployment)

| Priority | Item | Status |
|----------|------|--------|
| 🔴 | Session-Reader: tool label map for all built-in tools | Open |
| 🔴 | Preference-memory per DE (stop asking after 3 same rejections) | Open |
| 🟡 | DE-to-DE `inbox.jsonl` communication (fully tested end-to-end) | Open |
| 🟡 | Autonomy level system (Level 1→3 progression, manual trigger) | Concept ready, not implemented |
| 🟡 | Jefe / manager layer (visual org chart → active routing) | Deliberately deferred until DEs have track record |
| 🟢 | `bootstrap.sh`: initialize git tracking in `AGENTS_DIR` | Open |
| 🟢 | Health check script integration into startup | Open |

---

## Design decisions (not to revisit without reason)

| Decision | Rationale |
|----------|-----------|
| Jefe layer is visual-only (not active routing) | A manager without more authority than their reports adds complexity with no value. Activate only after DEs have track record and trust is established. |
| Validation Mode as default | All DEs start with everything → Decision. No autonomous external actions until the human explicitly grants it. Trust is earned. |
| Scheduler embedded in backend process | External cron is a dependency that fails silently. Embedded 30-min auto-trigger means the framework is self-contained. |
| No CDN for critical portal JS | CDN failure = blank page = broken portal. Bundle locally. One of the two things that must always work. |
| Free-text response to Decisions | Binary Approve/Reject loses nuance. The human's context goes back into the session as a message — the agent integrates it naturally. |
