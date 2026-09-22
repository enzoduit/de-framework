# KPI System — Digital Employee Framework

## Overview

Every DE has a `workspace/kpis.yaml` that defines its measurable KPIs. The generic `pre_fetch.py` reads this file, runs each measurement command, and emits a structured briefing before the ReAct loop starts — without any LLM call.

```
session starts
     │
     ▼
pre_fetch.py  ← reads kpis.yaml, runs measure commands (10s timeout each)
     │           writes metrics.json with new values + history
     ▼
briefing printed to stdout (injected as trigger_context)
     │
     ▼
ReAct loop begins with KPI state visible
```

## kpis.yaml Schema

```yaml
de: "<de_name>"           # must match directory name in /var/de-agents/
kpis:
  - id: <snake_case>      # unique identifier, also used as key in metrics.json
    name: <Human Name>    # shown in briefing
    target: <number>      # numeric target value
    unit: "%"             # display unit (%, leads, USD, pages, ...)
    direction: up         # up = higher is better, down = lower is better
    measure: "<command>"  # shell command run from DE_DIR, must print one value to stdout
    frequency: weekly     # daily | weekly | per_session (informational only, not enforced yet)
```

## Measurement Commands

The `measure` command runs with CWD = `/var/de-agents/<de>/` and a 10-second timeout.
It must print exactly one value to stdout:
- A number (int or float) → stored and compared against target
- `not_measured` → shown as ⚠ in briefing, not stored
- Empty / error → treated as not_measured

## Available measure_*.py Scripts

### `measure_soav.py`
Reads cached SoAV (Share of AI Voice) score. Deployed to all grow_* and geo DEs.

```
Reads: workspace/soav_latest.json → .soav_score or .soav_pct
       workspace/benchmark_*.json → .soav_pct (fallback, e.g. grow_agentic_living)
Outputs: 0.0–100.0 (percentage) or 'not_measured'
```

To populate the cache, the DE's benchmark script must write:
```json
// workspace/soav_latest.json
{"soav_score": 34.5, "timestamp": "2026-09-22T10:00:00Z"}
```

### `measure_sessions.py`
Scans all session files across all DEs for the last 7 days. Deployed to flow and max.

```
Usage: python3 workspace/measure_sessions.py --metric <metric>
Metrics:
  timed_out_rate  → % sessions with status=max_iterations_reached
  no_output_rate  → % sessions with no summary field
  total_sessions  → raw count
```

### `measure_cost.py`
Estimates cost from session step counts. Deployed to max.

```
Usage: python3 workspace/measure_cost.py --trigger <cron|all> --metric <metric>
Metrics:
  avg_cost    → average USD cost per matching session (default)
  waste_rate  → % sessions with no output
  total_cost  → total USD for period
Cost model: haiku=0.0003/step, sonnet=0.003/step, default=0.001/step
```

## metrics.json Format

Written to `/var/de-agents/<de>/metrics.json` after each pre_fetch run:

```json
{
  "last_updated": "2026-09-22T06:20:00Z",
  "kpis": [
    {
      "id": "soav_score",
      "name": "SoAV Score (Perplexity)",
      "target": 30,
      "unit": "%",
      "direction": "up",
      "value": 34.5,
      "updated": "2026-09-22T06:20:00Z",
      "history": [
        {"ts": "2026-09-15", "value": 28.0}
      ]
    }
  ]
}
```

`history` stores the last 10 previous values (only written on change).

## Briefing Format

```
=== GROW_MINIMIST BRIEFING — 2026-09-22 ===

OFF TRACK — action needed:
  ✗ Leads (charity retail directors): 1 leads (target: 3 leads)

Not yet measured:
  ⚠ SoAV Score (Perplexity): not measured (target: 30 %)

On track:
  ✓ Some KPI: 42 % (target: 30 %)

Active experiments:
  ## Experiment: ...

RULE: Address off-track KPIs first. One focused action per session.
```

## KPI Definitions by DE

| DE | KPI | Target | Source |
|----|-----|--------|--------|
| grow_minimist | SoAV Score | 30% | soav_latest.json |
| grow_minimist | Leads | 3 | workspace/leads.json |
| grow_agentfabric | SoAV Score | 25% | soav_latest.json |
| grow_agentic_living | SoAV Score | 30% | benchmark_*.json |
| growed | SoAV Score (personal brand) | 20% | soav_latest.json |
| grow_engelreal | SoAV Score | 30% | soav_latest.json |
| grow_flyraising | SoAV Score | 25% | soav_latest.json |
| grow_rflect | SoAV Score | 50% | soav_latest.json |
| grow_studyond | SoAV Score | 25% | soav_latest.json |
| grow_vwupass | SoAV Score | 30% | soav_latest.json |
| geo | SoAV Score | 30% | soav_latest.json |
| geo | Active satellite pages | 10 | workspace/pages.json |
| flow | Timed-out rate (7d) | ≤10% | session files |
| flow | No-output rate (7d) | ≤15% | session files |
| max | Avg cost per cron session | ≤$0.05 | session files |
| max | Waste rate (no output) | ≤20% | session files |
| coach | Training adherence | 90% | workspace/metrics_cache.json |
| scribe | Pending experiment docs | 0 | metrics.json |
| shield | Core services healthy | 100% | systemctl |
| growth | Weekly visitors | 100 | workspace/traffic_cache.json |

## Adding KPIs for a New DE

1. Create `/var/de-agents/<de>/workspace/kpis.yaml` following the schema above.
2. Copy `pre_fetch.py` from `de-framework/framework/` into the workspace.
3. If you need SoAV tracking, copy `measure_soav.py` too.
4. Test: `python3 /var/de-agents/<de>/workspace/pre_fetch.py`
5. Add an entry to this doc's table.

## Data Gaps (as of 2026-09-22)

These KPIs will show `not_measured` until the cache files are created:

| DE | KPI | Missing file | How to fix |
|----|-----|-------------|------------|
| All grow_* (most) | SoAV Score | workspace/soav_latest.json | Run Perplexity benchmark → write soav_latest.json |
| grow_minimist | Leads | workspace/leads.json | Create leads tracking → `{"leads": [...]}` |
| geo | Satellite pages | workspace/pages.json | Create pages tracking → `{"pages": [...]}` |
| coach | Training adherence | workspace/metrics_cache.json | Garmin sync → write metrics_cache.json |
| growth | Weekly visitors | workspace/traffic_cache.json | Analytics integration → write traffic_cache.json |

## Files

```
de-framework/framework/
├── pre_fetch.py          ← generic, deploy to all DE workspaces
├── measure_soav.py       ← for grow_*, geo
├── measure_sessions.py   ← for flow, max
├── measure_cost.py       ← for max
└── kpis/
    ├── grow_minimist.yaml
    ├── grow_agentfabric.yaml
    ├── grow_agentic_living.yaml
    ├── growed.yaml
    ├── grow_engelreal.yaml
    ├── grow_flyraising.yaml
    ├── grow_rflect.yaml
    ├── grow_studyond.yaml
    ├── grow_vwupass.yaml
    ├── geo.yaml
    ├── flow.yaml
    ├── max.yaml
    ├── coach.yaml
    ├── scribe.yaml
    ├── shield.yaml
    └── growth.yaml
```
