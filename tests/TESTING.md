# DE Framework — Testing Guide

This guide is for **setup agents** and **developers** who need to verify the framework is correctly configured before telling a user "it's working."

## Quick Start

```bash
# 1. Run unit tests (no live backend needed)
python3 -m pytest tests/unit/ -v

# 2. Run full integration health check (requires running backend)
python3 tests/health_check.py

# 3. Run with live DE session test (slow, ~90s)
python3 tests/health_check.py --live
```

## What Gets Tested

### Unit Tests (`tests/unit/`)
Run without a live backend. Safe to run in CI and during setup.

| Test Class | What it checks |
|---|---|
| `TestSoftCheckpoint` | Soft checkpoint fires at 70%, not twice, correct message |
| `TestMaxIterationsConfig` | `max_iterations_cron` is read from `de.json` in `session_runner.py` |
| `TestFeedbackDB` | `feedback.db` creates correctly, stores and retrieves entries |
| `TestDecisionQuality` | Decision validation enforces required fields |
| `TestOutputQuality` | Internal filesystem paths detected in outputs |
| `TestToolRegistration` | `request_human_decision`, `write_metric`, `ask_colleague`, `log_assumption`, `measure_assumption` all registered |

### Integration Tests (`tests/health_check.py`)
Require a running backend at `http://localhost:8769`.

| Category | Tests |
|---|---|
| 1. Backend Connectivity | API reachable, auth token valid, ≥5 agents in list |
| 2. Credentials | `cloudflare-config.json` present with all fields, GitHub + CF tokens valid |
| 3. Decision Flow | `/decisions` works, queue file readable, `/feedback` reachable, `feedback.db` accessible and not stale |
| 4. Learning Loop | `log_assumption` + `measure_assumption` registered, LEARNING_LOG.md exists, soft checkpoint in code |
| 5. DE Configuration | All GROW DEs have `max_iterations_cron ≥ 10`, all DEs configured, no DE exceeds ceiling of 20 |
| 6. Output Quality | Recent sessions/decisions don't contain internal filesystem paths |
| 7. Live Session | (--live only) Trigger test-agent, verify completion and reasoning steps |
| 8. Portal Endpoints | `/decisions`, `/tools`, `/decide`, `/feedback` all return correct status codes |

## Setup Agent Checklist

When setting up a fresh instance, run through this in order:

```bash
# Step 1: Install dependencies
pip install -r requirements.txt

# Step 2: Verify backend starts
systemctl start de-backend
sleep 3
systemctl is-active de-backend

# Step 3: Unit tests (catch any broken code before going live)
cd /path/to/de-framework
python3 -m pytest tests/unit/ -v
# Expected: all pass

# Step 4: Integration health check
python3 tests/health_check.py
# Fix any FAIL items before proceeding

# Step 5: Configure per-DE iteration limits in de.json
# GROW agents: max_iterations_cron = 15
# GEO: max_iterations_cron = 8
# Status DEs (flow, max, shield, scribe, coach): max_iterations_cron = 5

# Step 6: Run integration check again to confirm
python3 tests/health_check.py
# All tests must pass before telling the user "it's working"

# Step 7 (optional): Live session test
python3 tests/health_check.py --live
```

## Known Gaps (as of 2026-09-28)

These are tracked issues not yet fixed — tests will FAIL for these intentionally:

1. **feedback.db staleness** — If the portal feedback UI is broken, `feedback.db` may show no entries after Sep 13. Test `feedback.db received data recently` will WARN.

2. **Decision → DE re-trigger** — When Ed approves a decision with a note, the DE is NOT automatically re-triggered with that note as context. The `decision-execute-queue.jsonl` fills up but no DE reads it.

3. **Internal paths in summaries** — Some DEs still reference `/var/de-agents/` or `/tmp/` paths in their session summaries. Test `Recent sessions don't contain raw filesystem paths` may FAIL until all DEs are updated to use public portal URLs.

## CI Pipeline

Every push to `master` or `main` runs:
- Syntax check on all backend Python files
- Unit tests
- Structural checks (soft checkpoint, tool registration, etc.)

See `.github/workflows/ci.yml` for the full pipeline.

## Adding New Tests

When you add a feature to the framework, add a test for it:

1. **New tool** → add to `TestToolRegistration` in `tests/unit/test_react_engine.py`
2. **New API endpoint** → add to `check_portal_endpoints()` in `tests/health_check.py`
3. **New core behavior** → add a new `TestXxx` class in `tests/unit/`
4. **New credential requirement** → add to `check_credentials()` in `tests/health_check.py`

The rule: **if it can break silently, it needs a test.**
