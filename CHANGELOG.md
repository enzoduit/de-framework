# DE-Framework Changelog

## 2026-09-28 — Full System Stabilization

### New Features

**Workspace File Uploads** (commits `4007a04`, `f7f1b77`)
- Portal: "⬆️ Upload file" button in Workspace tab — any file type, multiple at once
- Auto text extraction on upload: PDF → pdftotext, DOCX → python-docx, XLSX → openpyxl
- DEs now see all workspace files in their context (not just .md files)
- Chat sessions include workspace context (MEMORY.md + file listing) inline

**Decisions UX** (commit `41c7d9c`)
- Two-section layout: "Needs Your Action" (expanded, newest-first) + "Resolved" (collapsed)
- Compact rows for resolved: DE name + title + status badge + date
- Backend returns resolved decisions (last 50) alongside pending

**Portal Document Viewer** (commit `cd3f04c`)
- DEs write `portal://dename/filename` links — no external URL needed
- Portal intercepts `portal://`, fetches document inline via apiFetch (Zero Trust safe)
- `create_document` tool now outputs portal:// embed

**Chat Improvements** (commits `d02b0fe`, `9f4f871`)
- Response now includes `"format": "markdown"` field — frontend must render with markdown renderer
- Input widget should be `<textarea>` (not `<input>`) for multiline support
- `/chat/<de>` endpoint tested in health_check.py

### Bug Fixes

**create_document tool registration** (commit `6667381`)
- Session runner runs as subprocess — `from backend.core.tool_implementations` failed silently
- Fix: 3-tier import (backend.core → direct → inline fallback)
- Now works in all execution contexts

**Soft Checkpoint + Iteration Limits** (commit `4d0637f`)
- ReAct loop fires a reflection message at 70% of max_iterations
- DE decides autonomously whether to continue — no hard cutoff mid-task
- `max_iterations_cron` configurable per DE in de.json

### What Other Agents Need To Do

```bash
# 1. Pull latest
git pull origin master

# 2. Run health checks (verifies your specific setup)
python3 tests/health_check.py

# 3. For full end-to-end verification (triggers a live DE session)
python3 tests/health_check.py --live
```

**Configure in de.json for each DE:**
```json
{
  "max_iterations_cron": 15
}
```
Recommended: GROW DEs → 15, GEO → 8, status-check DEs (FLOW, MAX, etc.) → 5

**Set in /etc/de-framework.env:**
```
DE_PUBLIC_URL=https://your-de-api-domain.com
```

### API Changes (for custom frontends)

- `POST /chat/<de>` response now includes `"format": "markdown"` field
- `GET /decisions` now returns `{pending: [...], resolved: [...], count: N}`
- `POST /de/<name>/workspace/upload` auto-extracts text from PDF/DOCX/XLSX

### Test Coverage

Run `python3 tests/health_check.py` for 30+ integration checks covering:
1. Backend health + auth
2. Credentials (auto-discovered from de-framework.env)
3. Decision & feedback flow
4. Learning loop (assumptions, LEARNING_LOG)
5. DE config (max_iterations_cron)
6. Output quality (no internal paths in summaries)
7. Portal endpoints incl. `/chat/<de>`
8. Workspace uploads (optional: `--live`)
