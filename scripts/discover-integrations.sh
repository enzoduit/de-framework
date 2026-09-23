#!/bin/bash
# discover-integrations.sh — Probe available client integrations
# Usage: bash scripts/discover-integrations.sh [--env /path/to/client.env]
# Output: integration status table + integrations.yaml template

set -euo pipefail

ENV_FILE="${1:-/etc/de-framework.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

echo ""
echo "[Integration Discovery Report]"
echo "=============================="
echo "Run at: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Env file: $ENV_FILE"
echo ""

READY=0
PARTIAL=0
MISSING=0
FAIL=0

declare -A RESULTS
declare -A NOTES

# ── Salesforce ──────────────────────────────────────────────────────────────
NAME="Salesforce"
if [[ -n "${SALESFORCE_TOKEN:-}" && -n "${SALESFORCE_INSTANCE_URL:-}" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $SALESFORCE_TOKEN" \
    "${SALESFORCE_INSTANCE_URL}/services/data/v58.0/sobjects" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    RESULTS[$NAME]="ready"; NOTES[$NAME]="GET /sobjects → $HTTP"; ((READY++))
    pass "$NAME — READ (HTTP $HTTP)"
  elif [[ "$HTTP" == "403" ]]; then
    RESULTS[$NAME]="partial"; NOTES[$NAME]="Auth OK but restricted (HTTP $HTTP)"; ((PARTIAL++))
    warn "$NAME — PARTIAL (HTTP $HTTP, check API user permissions)"
  else
    RESULTS[$NAME]="fail"; NOTES[$NAME]="HTTP $HTTP — check token or instance URL"; ((FAIL++))
    fail "$NAME — FAIL (HTTP $HTTP)"
  fi
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set SALESFORCE_TOKEN + SALESFORCE_INSTANCE_URL"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Meta Ads ─────────────────────────────────────────────────────────────────
NAME="Meta Ads"
if [[ -n "${META_ACCESS_TOKEN:-}" && -n "${META_ADS_ACCOUNT_ID:-}" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://graph.facebook.com/v19.0/${META_ADS_ACCOUNT_ID}/insights?access_token=${META_ACCESS_TOKEN}&date_preset=yesterday&fields=spend" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    RESULTS[$NAME]="ready"; NOTES[$NAME]="GET /insights → $HTTP"; ((READY++))
    pass "$NAME — READ (HTTP $HTTP)"
  elif [[ "$HTTP" == "400" ]]; then
    RESULTS[$NAME]="partial"; NOTES[$NAME]="Auth OK but query error (HTTP $HTTP) — check account ID format"; ((PARTIAL++))
    warn "$NAME — PARTIAL (HTTP $HTTP)"
  else
    RESULTS[$NAME]="fail"; NOTES[$NAME]="HTTP $HTTP"; ((FAIL++))
    fail "$NAME — FAIL (HTTP $HTTP)"
  fi
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set META_ACCESS_TOKEN + META_ADS_ACCOUNT_ID"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Google Ads ───────────────────────────────────────────────────────────────
NAME="Google Ads"
if [[ -n "${GOOGLE_ADS_DEVELOPER_TOKEN:-}" && -n "${GOOGLE_ADS_REFRESH_TOKEN:-}" ]]; then
  RESULTS[$NAME]="partial"; NOTES[$NAME]="Credentials present — not probed (requires OAuth flow)"; ((PARTIAL++))
  warn "$NAME — CREDENTIALS PRESENT (not probed — OAuth required)"
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set GOOGLE_ADS_DEVELOPER_TOKEN + GOOGLE_ADS_REFRESH_TOKEN + GOOGLE_ADS_CLIENT_ID + GOOGLE_ADS_CLIENT_SECRET"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── DataCrush ────────────────────────────────────────────────────────────────
NAME="DataCrush"
if [[ -n "${DATACRUSH_API_KEY:-}" && -n "${DATACRUSH_URL:-}" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $DATACRUSH_API_KEY" \
    "${DATACRUSH_URL}/api/v1/ping" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    RESULTS[$NAME]="ready"; NOTES[$NAME]="GET /ping → $HTTP"; ((READY++))
    pass "$NAME — READ (HTTP $HTTP)"
  else
    RESULTS[$NAME]="fail"; NOTES[$NAME]="HTTP $HTTP — check API key or URL"; ((FAIL++))
    fail "$NAME — FAIL (HTTP $HTTP) — may need IP whitelist"
  fi
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set DATACRUSH_API_KEY + DATACRUSH_URL"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Yoizen ───────────────────────────────────────────────────────────────────
NAME="Yoizen"
if [[ -n "${YOIZEN_API_KEY:-}" && -n "${YOIZEN_URL:-}" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $YOIZEN_API_KEY" \
    "${YOIZEN_URL}/contacts" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    RESULTS[$NAME]="ready"; NOTES[$NAME]="GET /contacts → $HTTP"; ((READY++))
    pass "$NAME — READ (HTTP $HTTP)"
  elif [[ "$HTTP" == "403" ]]; then
    RESULTS[$NAME]="partial"; NOTES[$NAME]="Auth OK but /contacts → 403 (request expanded scope)"; ((PARTIAL++))
    warn "$NAME — PARTIAL (HTTP $HTTP, missing scope)"
  else
    RESULTS[$NAME]="fail"; NOTES[$NAME]="HTTP $HTTP"; ((FAIL++))
    fail "$NAME — FAIL (HTTP $HTTP)"
  fi
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set YOIZEN_API_KEY + YOIZEN_URL"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Telegram ─────────────────────────────────────────────────────────────────
NAME="Telegram"
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    RESULTS[$NAME]="ready"; NOTES[$NAME]="Bot token valid (getMe → 200)"; ((READY++))
    pass "$NAME — READ-WRITE (token valid)"
  else
    RESULTS[$NAME]="fail"; NOTES[$NAME]="Token invalid (HTTP $HTTP)"; ((FAIL++))
    fail "$NAME — FAIL (HTTP $HTTP)"
  fi
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Power BI ──────────────────────────────────────────────────────────────────
NAME="Power BI"
if [[ -n "${POWERBI_CLIENT_ID:-}" && -n "${POWERBI_CLIENT_SECRET:-}" && -n "${POWERBI_TENANT_ID:-}" ]]; then
  RESULTS[$NAME]="partial"; NOTES[$NAME]="Credentials present — not probed (OAuth required)"; ((PARTIAL++))
  warn "$NAME — CREDENTIALS PRESENT (not probed)"
else
  RESULTS[$NAME]="missing"; NOTES[$NAME]="Set POWERBI_CLIENT_ID + POWERBI_CLIENT_SECRET + POWERBI_TENANT_ID"; ((MISSING++))
  fail "$NAME — MISSING credentials"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
TOTAL=$((READY + PARTIAL + MISSING + FAIL))
echo ""
echo "Summary: ${READY} ready, ${PARTIAL} partial, $((MISSING + FAIL)) missing/fail (${TOTAL} total)"
echo ""

# ── Generate integrations.yaml template ──────────────────────────────────────
OUTPUT="${2:-./integrations.yaml}"
cat > "$OUTPUT" <<YAML
# integrations.yaml — auto-generated by discover-integrations.sh
# $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# Edit status, add notes, commit (without secrets) to client workspace.

client: "FILL_ME"
discovered_at: "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

integrations:

  salesforce:
    status: ${RESULTS[Salesforce]}
    env_var: SALESFORCE_TOKEN
    instance_url_var: SALESFORCE_INSTANCE_URL
    notes: "${NOTES[Salesforce]}"
    setup_url: "https://help.salesforce.com/s/articleView?id=sf.user_security_token.htm"

  meta_ads:
    status: ${RESULTS[Meta Ads]}
    env_var: META_ACCESS_TOKEN
    account_id_var: META_ADS_ACCOUNT_ID
    notes: "${NOTES[Meta Ads]}"
    setup_url: "https://developers.facebook.com/docs/marketing-api/get-started"

  google_ads:
    status: ${RESULTS[Google Ads]}
    env_vars: [GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_REFRESH_TOKEN, GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET]
    notes: "${NOTES[Google Ads]}"
    setup_url: "https://developers.google.com/google-ads/api/docs/first-call/dev-token"

  datacrush:
    status: ${RESULTS[DataCrush]}
    env_var: DATACRUSH_API_KEY
    url_var: DATACRUSH_URL
    notes: "${NOTES[DataCrush]}"

  yoizen:
    status: ${RESULTS[Yoizen]}
    env_var: YOIZEN_API_KEY
    url_var: YOIZEN_URL
    notes: "${NOTES[Yoizen]}"

  telegram:
    status: ${RESULTS[Telegram]}
    env_var: TELEGRAM_BOT_TOKEN
    chat_id_var: TELEGRAM_CHAT_ID
    notes: "${NOTES[Telegram]}"
    purpose: "Human supervisor channel for Level-2 decisions"

  powerbi:
    status: ${RESULTS[Power BI]}
    env_vars: [POWERBI_CLIENT_ID, POWERBI_CLIENT_SECRET, POWERBI_TENANT_ID]
    notes: "${NOTES[Power BI]}"
    setup_url: "https://learn.microsoft.com/en-us/power-bi/developer/embedded/register-app"

YAML

echo "integrations.yaml written → $OUTPUT"
echo ""

# ── Missing integrations checklist ───────────────────────────────────────────
NEED_ACTION=false
for NAME in "Salesforce" "Meta Ads" "Google Ads" "DataCrush" "Yoizen" "Telegram" "Power BI"; do
  if [[ "${RESULTS[$NAME]}" == "missing" || "${RESULTS[$NAME]}" == "fail" ]]; then
    NEED_ACTION=true
    break
  fi
done

if [[ "$NEED_ACTION" == "true" ]]; then
  echo "── Action Required (send to client) ─────────────────────────────────────"
  for NAME in "Salesforce" "Meta Ads" "Google Ads" "DataCrush" "Yoizen" "Telegram" "Power BI"; do
    STATUS="${RESULTS[$NAME]}"
    if [[ "$STATUS" == "missing" || "$STATUS" == "fail" ]]; then
      echo "  ❌ $NAME — ${NOTES[$NAME]}"
    fi
  done
  echo ""
  echo "DEs that depend on missing integrations will start in benchmark mode"
  echo "using available data, and pick up the missing metrics once credentials arrive."
  echo ""
fi
