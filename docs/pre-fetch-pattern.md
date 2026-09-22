# Pre-Fetch Pattern — DE Framework

## What It Is

`pre_fetch.py` is a small Python script that runs **before the LLM starts**, injected by `session_runner.py` into the ReAct context. It pulls KPI data without any LLM calls — pure Python, reads files/APIs, prints a structured briefing to stdout.

**The key insight:** The ReAct loop used to start blind. Now it starts with a complete picture of the KPI state. The LLM reads the briefing and immediately knows: "KPI is on track → one log line → done" or "KPI is off → identify ONE action → done." No exploration, no guessing.

---

## How session_runner.py Uses It

See `backend/core/session_runner.py` lines ~107–130:

```python
pre_fetch_script = workspace_dir / 'pre_fetch.py'
if pre_fetch_script.exists():
    import subprocess as _sp
    try:
        result = _sp.run(
            ['python3', str(pre_fetch_script)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, 'AGENTS_DIR': str(AGENTS_DIR)}
        )
        if result.stdout.strip():
            trigger_context = result.stdout.strip() + '\n\n---\n\n' + trigger_context
    except Exception as _e:
        print(f'[session_runner] pre_fetch.py failed (non-fatal): {_e}')
```

Key points:
- Runs with `timeout=30` — must complete in under 30 seconds (aim for <5s)
- Output is **prepended** to `trigger_context` (before any user message or trigger data)
- Failure is non-fatal — session continues without briefing if script errors
- Gets `AGENTS_DIR` env variable pointing to `/var/de-agents`
- Must print to **stdout** (not stderr, not files)

---

## File Location

```
/var/de-agents/<de_name>/workspace/pre_fetch.py
```

The script is always in the DE's `workspace/` directory. This is where `session_runner.py` looks for it.

---

## What pre_fetch.py Should Do

1. **Read `metrics.json`** — the KPI store for this DE
2. **Read `workspace/experiments.md`** — active experiments
3. **Check any fast external source** (subprocess call with short timeout, no LLM)
4. **Print a structured briefing** to stdout — the format always starts with `=== [DE_NAME] BRIEFING — YYYY-MM-DD ===`

**Rules:**
- No LLM calls. Ever.
- No slow HTTP calls without a short timeout (max 4–5 seconds)
- Total runtime: <5 seconds
- If a data source doesn't exist yet, print a placeholder (don't crash)
- Use `AGENTS_DIR` env variable, not hardcoded paths

---

## Adding pre_fetch.py to a New DE

1. Copy the relevant template from below
2. Replace `DE_NAME` with the DE's folder name
3. Update the KPI section to match this DE's specific KPIs
4. Place at `/var/de-agents/<de_name>/workspace/pre_fetch.py`
5. Test: `python3 /var/de-agents/<de_name>/workspace/pre_fetch.py`

---

## Templates

### Kern-DE Template (metrics.json + experiments)

```python
#!/usr/bin/env python3
"""[DE_NAME] pre_fetch — [description], no LLM"""
import json, os
from datetime import datetime, timezone
from pathlib import Path

DE_NAME = '[de_name]'
AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
WORKSPACE = AGENTS_DIR / DE_NAME / 'workspace'

metrics_file = AGENTS_DIR / DE_NAME / 'metrics.json'
m = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}

kpis = m.get('kpis', [])
kpi_text = '\n'.join(
    f"  {k.get('name','?')}: {k.get('value','?')} / target {k.get('target','?')}"
    for k in kpis
) or '  (none tracked yet)'

exp = WORKSPACE / 'experiments.md'
experiments = exp.read_text()[:400] if exp.exists() else 'No experiments yet.'

print(f"""=== {DE_NAME.upper()} BRIEFING — {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ===
KPIs:
{kpi_text}

Active experiments:
{experiments}

RULE: Only act if KPI is off track or specific user request.""")
```

### Grow-Agent Template (SoAV + leads)

```python
#!/usr/bin/env python3
"""[de_name] pre_fetch — SoAV metrics from workspace, no LLM"""
import json, os
from datetime import datetime, timezone
from pathlib import Path

DE_NAME = '[de_name]'
AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
WORKSPACE = AGENTS_DIR / DE_NAME / 'workspace'

soav_cache = WORKSPACE / 'soav_latest.json'
s = json.loads(soav_cache.read_text()) if soav_cache.exists() else {}

soav_history_file = AGENTS_DIR / DE_NAME / 'soav_history.json'
soav_history = json.loads(soav_history_file.read_text()) if soav_history_file.exists() else []

metrics_file = AGENTS_DIR / DE_NAME / 'metrics.json'
m = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}

kpis = m.get('kpis', [])
kpi_text = '\n'.join(
    f"  {k.get('name','?')}: {k.get('value','?')} / target {k.get('target','?')}"
    for k in kpis[:5]
) or '  (no KPIs tracked yet)'

exp = WORKSPACE / 'experiments.md'
experiments = exp.read_text()[:500] if exp.exists() else 'No experiments yet.'

last_soav = s.get('soav_score', 'not measured yet')
last_benchmark = s.get('timestamp', 'never')
if soav_history and isinstance(soav_history, list) and soav_history:
    latest = soav_history[-1]
    last_soav = latest.get('soav_pct', last_soav)
    last_benchmark = latest.get('date', last_benchmark)

print(f"""=== {DE_NAME.upper()} BRIEFING — {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ===
SoAV (Share of AI Voice):
  Current: {last_soav}
  Last measured: {last_benchmark}

KPIs:
{kpi_text}

Active experiments:
{experiments}

NEXT ACTION: Run Perplexity benchmark to update SoAV, then decide ONE action based on gap analysis.""")
```

---

## Workspace Files Required

Every DE's workspace should have:

| File | Purpose |
|------|---------|
| `pre_fetch.py` | Runs before LLM; injects KPI briefing |
| `experiments.md` | Log of experiments: change made, KPI before/after, outcome |
| `log.md` | One-line per session: date, trigger, KPI value, status |
| `soav_latest.json` | (grow_* only) Latest SoAV benchmark result |

---

## Session-Type-Routing

Every `job.md` starts with a `## STOP — Read trigger_type before doing ANYTHING.` block that defines behavior for each trigger:

| trigger_type | Max iterations | Behavior |
|---|---|---|
| `cron` | 5 | Read briefing → on track: log line → done; off track: ONE action or decision |
| `user` + "Decision resolved" | 5 | Execute ONE approved action → log to experiments.md → schedule check-in |
| `experiment_followup` | 8 | Measure KPI → compare → keep or revert → log outcome |
| `user` (direct) | 10 | Do exactly what was asked |
| unclear | 1 | Log "Session skipped" → done |

This routing block is always at the top of `job.md`, right after the H1 heading.

---

## Active DEs (as of 2026-09-22)

| DE | Type | pre_fetch.py | Primary KPI |
|---|---|---|---|
| `max` | Kern | ✓ (original) | Monthly spend ≤ $500 |
| `flow` | Kern | ✓ | Avg user messages/task |
| `coach` | Kern | ✓ | Training adherence / Garmin data |
| `scribe` | Kern | ✓ | Pending experiments → 0 |
| `shield` | Kern | ✓ | Open vulnerabilities → 0 |
| `growth` | Kern | ✓ | 100 visitors/week agentic-living.com |
| `geo` | Kern | ✓ | SoAV brand ≥18/33 |
| `grow_minimist` | Grow | ✓ | 3 leads + SoAV ≥30% |
| `grow_agentfabric` | Grow | ✓ | 10 paying customers |
| `grow_agentic_living` | Grow | ✓ | 9 leads (3 per segment) |
| `growed` | Grow | ✓ | SoAV ≥40% on 13 queries |
| `grow_engelreal` | Grow | ✓ | 3 leads für engelreal.at |
| `grow_flyraising` | Grow | ✓ | SoAV |
| `grow_rflect` | Grow | ✓ | SoAV DACH academic |
| `grow_studyond` | Grow | ✓ | SoAV |
| `grow_vwupass` | Grow | ✓ | SoAV |
| `ops` | Ops | — | (own logic, skip) |
| `aria` | Special | — | (own logic, skip) |
