#!/bin/bash
# new-client-setup.sh — Bootstrap directory structure for a new DE team client
#
# Usage:
#   bash new-client-setup.sh <client-name> <de1> <de2> ... <deN>
#
# Examples:
#   bash new-client-setup.sh acme grow_acme content_acme ops_acme
#   bash new-client-setup.sh lftw grow_lftw content_transversal chief_lftw
#
# What this creates for each DE:
#   /var/de-agents/<de>/
#   ├── workspace/
#   │   ├── kpis.yaml          (empty template — fill in manually)
#   │   ├── pre_fetch.py       (copied from framework/)
#   │   ├── experiments.md     (empty)
#   │   └── log.md             (empty)
#   ├── logs/
#   ├── sessions/
#   ├── job.md                 (empty template — fill in manually)
#   ├── de.json                (skeleton with name and role)
#   ├── memory.md              (empty stub)
#   ├── metrics.json           (empty stub)
#   ├── decisions.json         ({"pending": []})
#   └── inbox.jsonl            (empty)
#
# After running this script, you still need to:
#   [1] Fill in job.md for each DE (see examples/job-template.md)
#   [2] Fill in kpis.yaml with real KPI definitions
#   [3] Register cron schedules via openclaw cron add
#   [4] Add each DE to docs/de-inventory.md
# ---------------------------------------------------------------------------

set -e

# ── Args ────────────────────────────────────────────────────────────────────
if [ "$#" -lt 2 ]; then
  echo "Usage: bash new-client-setup.sh <client-name> <de1> [<de2> ...]"
  echo ""
  echo "Example:"
  echo "  bash new-client-setup.sh acme grow_acme content_acme ops_acme"
  exit 1
fi

CLIENT_NAME="$1"
shift
DE_NAMES=("$@")

# ── Paths ───────────────────────────────────────────────────────────────────
AGENTS_DIR="${AGENTS_DIR:-/var/de-agents}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_DIR="$(dirname "$SCRIPT_DIR")/framework"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/examples"
PRE_FETCH_SRC="$FRAMEWORK_DIR/pre_fetch.py"
JOB_TEMPLATE_SRC="$TEMPLATE_DIR/job-template.md"

# ── Shared workspace for the client (used by chief agents) ──────────────────
SHARED_DIR="$AGENTS_DIR/$CLIENT_NAME/shared"

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DE Framework — New Client Setup"
echo "  Client: $CLIENT_NAME"
echo "  DEs:    ${DE_NAMES[*]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Create shared workspace ──────────────────────────────────────────────────
echo "Creating shared workspace for client '$CLIENT_NAME'..."
mkdir -p "$SHARED_DIR"/{briefs,reports,decisions}

if [ ! -f "$SHARED_DIR/decisions/pending.json" ]; then
  echo '{"decisions": []}' > "$SHARED_DIR/decisions/pending.json"
fi

echo -e "${GREEN}✓${NC} $SHARED_DIR/{briefs,reports,decisions}"

# ── Create directories for each DE ──────────────────────────────────────────
for DE in "${DE_NAMES[@]}"; do
  DE_DIR="$AGENTS_DIR/$DE"
  WORKSPACE="$DE_DIR/workspace"

  echo ""
  echo "Setting up: $DE"

  # Main directories
  mkdir -p "$DE_DIR"/{workspace,logs,sessions}

  # ── workspace/pre_fetch.py ──
  if [ -f "$PRE_FETCH_SRC" ]; then
    cp "$PRE_FETCH_SRC" "$WORKSPACE/pre_fetch.py"
    echo -e "  ${GREEN}✓${NC} workspace/pre_fetch.py (copied from framework/)"
  else
    echo -e "  ${RED}✗${NC} workspace/pre_fetch.py — framework/pre_fetch.py not found at $PRE_FETCH_SRC"
    echo "  ⚠ Copy manually: cp <de-framework>/framework/pre_fetch.py $WORKSPACE/pre_fetch.py"
  fi

  # ── workspace/kpis.yaml ──
  if [ ! -f "$WORKSPACE/kpis.yaml" ]; then
    cat > "$WORKSPACE/kpis.yaml" << KPIS_TEMPLATE
de: "${DE}"
kpis:
  # TODO: Replace this example with real KPIs from the job description
  # See docs/kpi-system.md for full schema + Benchmark Mode instructions
  - id: example_kpi
    name: "Example KPI — Replace Me"
    description: "TODO: What does this DE measure?"
    measure: "echo 'not_measured'"
    unit: "unit"
    direction: "up"          # up = higher is better, lower_is_better for costs/churn
    target: null             # null = will be auto-set from first measurement (benchmark mode)
    target_auto: true        # enable benchmark mode when no historical data available
    target_improvement: 0.10 # 10% improvement from baseline
    frequency: weekly        # daily | weekly | per_session
KPIS_TEMPLATE
    echo -e "  ${GREEN}✓${NC} workspace/kpis.yaml (template — fill in real KPIs)"
  else
    echo -e "  ${YELLOW}~${NC} workspace/kpis.yaml already exists — skipped"
  fi

  # ── workspace/experiments.md ──
  if [ ! -f "$WORKSPACE/experiments.md" ]; then
    cat > "$WORKSPACE/experiments.md" << 'EXPERIMENTS_TEMPLATE'
# Experiments Log

## No experiments yet.

<!-- Format for new experiments:
## [Short description] — [date]
- Change made: [what exactly]
- KPI before: [value]
- Expected KPI after: [value, with reasoning]
- Check-in date: [date]
- Outcome: [filled in on check-in]
-->
EXPERIMENTS_TEMPLATE
    echo -e "  ${GREEN}✓${NC} workspace/experiments.md (empty)"
  else
    echo -e "  ${YELLOW}~${NC} workspace/experiments.md already exists — skipped"
  fi

  # ── workspace/log.md ──
  if [ ! -f "$WORKSPACE/log.md" ]; then
    echo "# Session Log — ${DE}" > "$WORKSPACE/log.md"
    echo "" >> "$WORKSPACE/log.md"
    echo "<!-- One line per session: [date] trigger=[type] kpi=[value] status=[ok|off|blocked] -->" >> "$WORKSPACE/log.md"
    echo -e "  ${GREEN}✓${NC} workspace/log.md (empty)"
  else
    echo -e "  ${YELLOW}~${NC} workspace/log.md already exists — skipped"
  fi

  # ── job.md ──
  if [ ! -f "$DE_DIR/job.md" ]; then
    if [ -f "$JOB_TEMPLATE_SRC" ]; then
      cp "$JOB_TEMPLATE_SRC" "$DE_DIR/job.md"
      # Replace the placeholder name
      sed -i "s/\[DE NAME\]/${DE}/g" "$DE_DIR/job.md"
      echo -e "  ${GREEN}✓${NC} job.md (from template — fill in role, mission, KPIs)"
    else
      echo "# ${DE} — [Role Title]" > "$DE_DIR/job.md"
      echo "" >> "$DE_DIR/job.md"
      echo "**Mission:** [One sentence: what metric/outcome this DE owns.]" >> "$DE_DIR/job.md"
      echo "" >> "$DE_DIR/job.md"
      echo "**KPI:** [Specific measurable target]" >> "$DE_DIR/job.md"
      echo "" >> "$DE_DIR/job.md"
      echo "**Measured by:** [Exactly how to calculate it]" >> "$DE_DIR/job.md"
      echo -e "  ${GREEN}✓${NC} job.md (minimal stub — template not found at $JOB_TEMPLATE_SRC)"
    fi
  else
    echo -e "  ${YELLOW}~${NC} job.md already exists — skipped"
  fi

  # ── de.json ──
  if [ ! -f "$DE_DIR/de.json" ]; then
    cat > "$DE_DIR/de.json" << DE_JSON_TEMPLATE
{
  "name": "${DE}",
  "display_name": "TODO: Display Name",
  "role": "TODO: Role Title",
  "color": "#10B981",
  "mission": "TODO: One sentence mission.",
  "kpis": [],
  "responsibilities": {
    "level_0": ["TODO: What this DE does without asking"],
    "level_1": ["TODO: What this DE does and logs"],
    "level_2": ["TODO: What this DE escalates to human"]
  },
  "hard_constraints": [],
  "data_sources": [],
  "triggers": ["cron"],
  "colleagues": [],
  "cron_id": "TODO: Register with openclaw cron add"
}
DE_JSON_TEMPLATE
    echo -e "  ${GREEN}✓${NC} de.json (skeleton — fill in display_name, role, mission)"
  else
    echo -e "  ${YELLOW}~${NC} de.json already exists — skipped"
  fi

  # ── memory.md ──
  if [ ! -f "$DE_DIR/memory.md" ]; then
    echo "# Memory — ${DE}" > "$DE_DIR/memory.md"
    echo "" >> "$DE_DIR/memory.md"
    echo "<!-- Persistent memory written by the agent across sessions. -->" >> "$DE_DIR/memory.md"
    echo -e "  ${GREEN}✓${NC} memory.md (empty stub)"
  else
    echo -e "  ${YELLOW}~${NC} memory.md already exists — skipped"
  fi

  # ── metrics.json ──
  if [ ! -f "$DE_DIR/metrics.json" ]; then
    cat > "$DE_DIR/metrics.json" << METRICS_JSON
{
  "agent": "${DE}",
  "role": "TODO",
  "last_session": null,
  "last_updated": null,
  "sessions_total": 0,
  "kpis": [],
  "self_evaluation": {
    "status": "onboarding",
    "note": "First session not yet run.",
    "score": null
  }
}
METRICS_JSON
    echo -e "  ${GREEN}✓${NC} metrics.json (empty stub)"
  else
    echo -e "  ${YELLOW}~${NC} metrics.json already exists — skipped"
  fi

  # ── decisions.json ──
  if [ ! -f "$DE_DIR/decisions.json" ]; then
    echo '{"pending": []}' > "$DE_DIR/decisions.json"
    echo -e "  ${GREEN}✓${NC} decisions.json"
  else
    echo -e "  ${YELLOW}~${NC} decisions.json already exists — skipped"
  fi

  # ── inbox.jsonl ──
  if [ ! -f "$DE_DIR/inbox.jsonl" ]; then
    touch "$DE_DIR/inbox.jsonl"
    echo -e "  ${GREEN}✓${NC} inbox.jsonl (empty)"
  else
    echo -e "  ${YELLOW}~${NC} inbox.jsonl already exists — skipped"
  fi

done

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete for client: $CLIENT_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Directories created: ${DE_NAMES[*]}"
echo "✅ Shared workspace: $SHARED_DIR"
echo ""
echo "📋 STILL REQUIRED — complete these manually:"
echo ""
echo "  [1] Fill in job.md for each DE:"
for DE in "${DE_NAMES[@]}"; do
  echo "        $AGENTS_DIR/$DE/job.md"
done
echo ""
echo "  [2] Fill in kpis.yaml with real KPI definitions:"
for DE in "${DE_NAMES[@]}"; do
  echo "        $AGENTS_DIR/$DE/workspace/kpis.yaml"
done
echo ""
echo "  [3] Test pre_fetch.py for each DE:"
for DE in "${DE_NAMES[@]}"; do
  echo "        python3 $AGENTS_DIR/$DE/workspace/pre_fetch.py"
done
echo ""
echo "  [4] Register cron schedules (one per DE):"
echo "        openclaw cron add --name '<de>-cron' --schedule '0 9 */2 * *' \\"
echo "          --command '/var/de-agents/de-trigger.sh <de> cron' --session isolated"
echo ""
echo "  [5] Update de.json for each DE (display_name, role, mission)"
echo ""
echo "  [6] Add each DE to docs/de-inventory.md"
echo ""
echo "  [7] Verify registration:"
echo "        TOKEN=\$(grep '^DE_API_TOKEN=' /etc/de-framework.env | cut -d= -f2)"
echo "        curl -s -H \"Authorization: Bearer \$TOKEN\" http://localhost:8769/de-list"
echo ""
echo "  See QUICKSTART.md for full step-by-step instructions."
echo ""
