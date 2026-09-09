#!/usr/bin/env bash
# ============================================================
# bootstrap.sh — Digital Employees Framework — One-shot setup
# Run once on a fresh Ubuntu 20.04+ server:
#   sudo bash bootstrap.sh
# Safe to run multiple times (idempotent).
# ============================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/etc/de-framework.env"
AGENTS_DIR="/var/de-agents"
SERVICE_NAME="de-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_CONF="/etc/nginx/sites-available/de-api"
CRON_FILE="/etc/cron.d/de-framework-scheduler"
PORT=8769

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warning() { echo -e "${YELLOW}[bootstrap]${NC} $*"; }

# ── 1. System dependencies ────────────────────────────────────────────────────
info "Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    nginx curl gnupg2 \
    cron \
    2>/dev/null

# Node.js (for wrangler / CF Pages deploy) — install only if missing
if ! command -v node &>/dev/null; then
    info "Installing Node.js 18..."
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - 2>/dev/null
    apt-get install -y -qq nodejs 2>/dev/null
else
    info "Node.js already installed: $(node --version)"
fi

# npx / wrangler (global)
if ! npx --version &>/dev/null 2>&1; then
    npm install -g npm@latest --quiet
fi

# ── 2. Python dependencies ────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip3 install -q -r "${REPO_DIR}/requirements.txt"

# ── 3. Agents directory structure ─────────────────────────────────────────────
info "Creating agents directory: ${AGENTS_DIR}"
mkdir -p "${AGENTS_DIR}"
chmod 755 "${AGENTS_DIR}"

# ── 4. Environment file ───────────────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
    info "Creating ${ENV_FILE} with placeholders..."
    cat > "${ENV_FILE}" <<EOF
# Digital Employees Framework — Environment Variables
# Edit this file, then: systemctl restart ${SERVICE_NAME}

# Required: Anthropic API key (get at https://console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME

# Required: Bearer token protecting all API endpoints (choose any secret string)
DE_API_TOKEN=REPLACE_WITH_STRONG_SECRET

# Optional: OpenClaw gateway (if running alongside OpenClaw)
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=REPLACE_ME_OR_LEAVE_EMPTY

# Model used by all DEs (override per-DE in de.json → "model" field)
DE_MODEL=claude-haiku-4-5

# Agents directory (all DE configs and sessions live here)
AGENTS_DIR=${AGENTS_DIR}

# Backend port
DE_API_PORT=${PORT}
EOF
    chmod 600 "${ENV_FILE}"
    warning "Created ${ENV_FILE} with placeholders. Fill in real values before starting the service."
else
    info "${ENV_FILE} already exists — skipping creation."
fi

# ── 5. Systemd service ────────────────────────────────────────────────────────
SERVICE_SRC="${REPO_DIR}/deploy/de-backend.service"

if [ ! -f "${SERVICE_FILE}" ]; then
    info "Installing systemd service: ${SERVICE_FILE}"
    if [ -f "${SERVICE_SRC}" ]; then
        cp "${SERVICE_SRC}" "${SERVICE_FILE}"
    else
        # Write inline if deploy/de-backend.service doesn't exist yet
        cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Digital Employees Framework Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/python3 backend/server.py
Restart=always
RestartSec=5
StandardOutput=append:/tmp/de-backend.log
StandardError=append:/tmp/de-backend.log

[Install]
WantedBy=multi-user.target
EOF
    fi
    chmod 644 "${SERVICE_FILE}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" 2>/dev/null || true
    info "Service installed and enabled."
else
    info "Systemd service already installed — reloading daemon."
    systemctl daemon-reload
fi

# ── 6. Nginx config ───────────────────────────────────────────────────────────
if [ ! -f "${NGINX_CONF}" ]; then
    info "Installing nginx config: ${NGINX_CONF}"
    cat > "${NGINX_CONF}" <<EOF
# DE Framework API — nginx reverse proxy
# Proxies /api/* to the Python backend on port ${PORT}
# Adjust server_name and add SSL (certbot) for production.

server {
    listen 80;
    server_name _;          # Replace with your domain in production

    # Increase timeout for long-running sessions
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;

    location / {
        proxy_pass         http://127.0.0.1:${PORT};
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   Authorization \$http_authorization;
        proxy_pass_header  Authorization;
    }
}
EOF

    # Enable site (symlink)
    if [ ! -L /etc/nginx/sites-enabled/de-api ]; then
        ln -s "${NGINX_CONF}" /etc/nginx/sites-enabled/de-api 2>/dev/null || true
    fi

    # Remove default nginx site that blocks port 80
    rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

    nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || \
        warning "nginx config written but reload failed — check nginx manually"

    info "Nginx config installed."
else
    info "Nginx config already exists at ${NGINX_CONF} — skipping."
fi

# ── 7. Cron scheduler ─────────────────────────────────────────────────────────
if [ ! -f "${CRON_FILE}" ]; then
    info "Installing cron scheduler: ${CRON_FILE}"
    cat > "${CRON_FILE}" <<EOF
# DE Framework — triggers scheduled DE sessions every minute
# Calls /trigger-scheduled on the backend (no auth required — localhost only)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
* * * * * root curl -sf http://127.0.0.1:${PORT}/trigger-scheduled > /tmp/de-cron.log 2>&1
EOF
    chmod 644 "${CRON_FILE}"
    # Restart cron to pick up new file
    systemctl restart cron 2>/dev/null || service cron restart 2>/dev/null || true
    info "Cron scheduler installed."
else
    info "Cron scheduler already exists at ${CRON_FILE} — skipping."
fi

# ── 8. Deploy directory (ensure service file source exists for future runs) ───
mkdir -p "${REPO_DIR}/deploy"
if [ ! -f "${SERVICE_SRC}" ]; then
    cp "${SERVICE_FILE}" "${SERVICE_SRC}" 2>/dev/null || true
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  DE Framework bootstrap complete!"
echo "======================================================"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit the environment file:"
echo "       nano ${ENV_FILE}"
echo "     Fill in:"
echo "       ANTHROPIC_API_KEY  — your Anthropic key"
echo "       DE_API_TOKEN       — choose a strong secret"
echo ""
echo "  2. Start the backend:"
echo "       systemctl start ${SERVICE_NAME}"
echo "       systemctl status ${SERVICE_NAME}"
echo ""
echo "  3. Verify it's running:"
echo "       curl http://127.0.0.1:${PORT}/health"
echo ""
echo "  4. Deploy the portal (optional):"
echo "       cd ${REPO_DIR}"
echo "       npx wrangler pages deploy portal/ --project-name my-de-portal"
echo ""
echo "  5. Create your first DE via API:"
echo '       curl -s -X POST http://127.0.0.1:'"${PORT}"'/api/des \'
echo '         -H "Authorization: Bearer \$DE_API_TOKEN" \'
echo '         -H "Content-Type: application/json" \'
echo '         -d '"'"'{"name":"ops","role":"Operations Manager","mission":"Keep services up"}'"'"
echo ""
echo "  Logs: tail -f /tmp/de-backend.log"
echo "======================================================"
echo ""
echo "🎨 Optional: configure branding"
echo "   Edit /var/de-framework-branding.json or use the portal Settings → Branding"
echo "   See SETUP.md → White-Label / Branding for details"
