# DE Inventory — Digital Employee Roster

_Last updated: 2026-09-22_

All DEs live in `/var/de-agents/<name>/`. Triggered via `/var/de-agents/de-trigger.sh <name>`.
Token source: `/etc/de-framework.env` (never embedded in commands).

---

## Core Services

### OPS — Operations Manager
| Field | Value |
|-------|-------|
| **Mission** | Ensures all services, websites, and automated processes run 24/7. Detects outages, self-heals autonomously. |
| **KPIs** | Uptime % (de-backend, krisp-proxy, human-input-api, decisions-api, canvas-server, costs-dashboard); Auto-remediated incidents/24h |
| **Schedule** | Every 2h (`0 */2 * * *`) |
| **Cron ID** | `187d89a8-aa92-45a7-981c-ae10e0c08e48` |
| **Workspace** | `kpis.yaml` ✓ · `pre_fetch.py` ✓ · `experiments.md` ✓ · `log.md` ✓ · `incidents.log` (auto-created) |

### MAX — Cost Controller
| Field | Value |
|-------|-------|
| **Mission** | Tracks OpenClaw AI spend, flags waste, keeps costs below budget. |
| **KPIs** | Avg cost/cron session (target ≤$0.05); Waste rate (target ≤20%) |
| **Schedule** | Daily 06:00 (`0 6 * * *`) |
| **Cron ID** | `87e64317-4ee2-4d2c-b8cc-4e2ba436acfd` |
| **Workspace** | `kpis.yaml` ✓ · `pre_fetch.py` ✓ · `experiments.md` ✓ · `log.md` ✓ |

### SHIELD — Data Security Officer
| Field | Value |
|-------|-------|
| **Mission** | Scans public-facing assets for credential leaks and security vulnerabilities. |
| **KPIs** | Open vulnerabilities (target 0); Last scan <24h; Auto-fixed issues; Compliance log entries |
| **Schedule** | Daily 07:00 (`0 7 * * *`) |
| **Cron ID** | `6ca1a829-3a61-45c9-8c00-865d7d5edeec` |
| **Workspace** | `kpis.yaml` ✓ · `pre_fetch.py` ✓ · `experiments.md` ✓ · `log.md` ✓ |
| **Note** | Service recovery removed from Level 0 (2026-09-22) — belongs in OPS |

---

## Productivity / Internal

### FLOW — Session Quality
| Field | Value |
|-------|-------|
| **Mission** | Ensures Ed's OpenClaw sessions are high quality and cost-effective. |
| **Schedule** | Daily 08:00 (`0 8 * * *`) |
| **Cron ID** | `f8aa3873-259b-4cb0-a922-13aaf5743275` |
| **Workspace** | Full ✓ |

### COACH — Performance Coach
| Field | Value |
|-------|-------|
| **Mission** | Monitors Ed's endurance training and performance metrics. |
| **Schedule** | Daily 08:30 (`30 8 * * *`) |
| **Cron ID** | `cdcadb05-888b-4e1f-86ff-d3098ddfc469` |
| **Workspace** | Full ✓ |

### SCRIBE — Meeting Intelligence
| Field | Value |
|-------|-------|
| **Mission** | Transcribes and processes Krisp recordings. |
| **Schedule** | **No schedule** — webhook-triggered via Krisp |
| **Cron ID** | — |
| **Workspace** | Full ✓ |

---

## Product

### ARIA — Head of Product · Agent School
| Field | Value |
|-------|-------|
| **Mission** | Agent School grows daily active users and improves how people work with AI agents. |
| **KPIs** | Server uptime (target 1); nginx up (target 1); Situations total (growing); Sessions completed |
| **Schedule** | Mon + Thu 09:00 (`0 9 * * 1,4`) |
| **Cron ID** | `302082bb-f45a-4f0a-b1c5-b118654340ce` |
| **Workspace** | `kpis.yaml` ✓ · `pre_fetch.py` ✓ · `experiments.md` ✓ · `log.md` ✓ |

---

## Growth / GEO

### GROWTH — Growth Strategist
| Field | Value |
|-------|-------|
| **Mission** | Overall growth strategy and weekly review. |
| **Schedule** | Monday 09:00 (`0 9 * * 1`) |
| **Cron ID** | `c89c6d14-97bf-48eb-9fc6-72f34c572dc8` |
| **Workspace** | Full ✓ |

### GEO — LLM Visibility Optimizer
| Field | Value |
|-------|-------|
| **Mission** | Maximizes Ed's visibility in LLM-generated answers (Claude, Perplexity, etc.). |
| **Schedule** | Sun/Tue/Thu 23:00 (`0 23 * * 0,2,4`) |
| **Cron ID** | `b98bce59-4689-4999-a9a8-752605ec4d17` |
| **Workspace** | Full ✓ |
| **Note** | Also existed as shell cron; now in openclaw scheduler |

---

## GEO Vertical Agents (run every 2 days, staggered)

| DE | Target | Schedule | Cron ID |
|----|--------|----------|---------|
| **grow_minimist** | Minimist (Jordan Fitzgerald, UK charity retail SaaS) | `0 9 * * */2` | `e6eed2eb-77b0-46d6-90ca-071c10df7d0a` |
| **grow_agentfabric** | AgentFabric | `0 9 * * */2` | `3253c75d-1748-4e10-b813-364be60f49cd` |
| **grow_agentic_living** | Agentic Living | `0 10 * * */2` | `0daeb606-30d2-4cca-9025-da7c1fb57220` |
| **growed** | GrowEd (Ed's own content/GEO) | `0 10 * * */2` | `b07c5138-ca8b-4c18-84db-d78921e8d29c` |
| **grow_engelreal** | Engel Real | `0 11 * * */2` | `d08cf9b0-7298-4363-90ed-e97ed6b95f20` |
| **grow_flyraising** | FlyRaising | `0 11 * * */2` | `2a813f00-6817-4ebb-8431-a56e2d5afd9a` |
| **grow_rflect** | Rflect | `0 12 * * */2` | `ba25d667-31ab-4947-a48c-ddecc74fd26c` |
| **grow_studyond** | StudyOnd | `0 12 * * */2` | `4c1ad433-a54b-4c6a-a7c0-610d974e4bd7` |
| **grow_vwupass** | vwupass | `0 13 * * */2` | `276be5b8-96f6-4b7a-9b72-e4be9b30d048` |

---

## Trigger Infrastructure

```bash
# Trigger any DE manually:
/var/de-agents/de-trigger.sh <de_name> [trigger_type]
# trigger_type: cron (default), user, experiment_followup

# All cron IDs registered in openclaw scheduler (session=isolated)
# Token read from /etc/de-framework.env at runtime — never embedded
```

---

## Workspace Checklist

Every DE should have:
- `workspace/kpis.yaml` — KPI definitions with measure commands
- `workspace/pre_fetch.py` — pre-LLM data fetch, builds briefing
- `workspace/experiments.md` — active experiments log
- `workspace/log.md` — session log entries

Status as of 2026-09-22:

| DE | kpis.yaml | pre_fetch.py | experiments.md | log.md |
|----|-----------|--------------|----------------|--------|
| ops | ✅ (new) | ✅ (new) | ✅ (new) | ✅ (new) |
| aria | ✅ (new) | ✅ (new) | ✅ (new) | ✅ (new) |
| max | ✅ | ✅ | ✅ (new) | ✅ (new) |
| shield | ✅ | ✅ | ✅ | ✅ |
| flow | ✅ | ✅ | ✅ | ✅ |
| coach | ✅ | ✅ | ✅ | ✅ |
| growth | ✅ | ✅ | ✅ | ✅ |
| geo | ✅ | ✅ | ✅ | ✅ |
| scribe | ✅ | ✅ | ✅ | ✅ |
| grow_* (9x) | ✅ | ✅ | ✅ | ✅ |
