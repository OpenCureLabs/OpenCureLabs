#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# OpenCure Labs — DigitalOcean Droplet Setup
#
# Run on a fresh Ubuntu 24.04 droplet:
#   curl -sL https://raw.githubusercontent.com/OpenCureLabs/OpenCureLabs/main/deploy/setup-droplet.sh | bash
#
# Or after cloning:
#   bash deploy/setup-droplet.sh
#
# Prerequisites:
#   - Ubuntu 24.04 LTS droplet (Recommended: 2 vCPU / 4 GB RAM — $24/mo)
#   - Domain A record pointing to droplet IP (e.g., opencurelabs.ai → 1.2.3.4)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="${OPENCURE_DOMAIN:-opencurelabs.ai}"
APP_USER="opencure"
APP_DIR="/opt/opencurelabs"
REPO="https://github.com/OpenCureLabs/OpenCureLabs.git"

echo "═══════════════════════════════════════════════════════════"
echo "  OpenCure Labs — Droplet Setup"
echo "  Domain: ${DOMAIN}"
echo "═══════════════════════════════════════════════════════════"

# ── 1. System packages ──────────────────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  postgresql postgresql-contrib \
  git curl ufw debian-keyring debian-archive-keyring apt-transport-https

# ── 2. Install Caddy (reverse proxy + auto TLS) ─────────────────────────
echo "[2/8] Installing Caddy..."
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq
apt-get install -y -qq caddy

# ── 3. Create app user ──────────────────────────────────────────────────
echo "[3/8] Creating app user..."
if ! id "${APP_USER}" &>/dev/null; then
  useradd --system --create-home --shell /bin/bash "${APP_USER}"
fi

# ── 4. Clone repo ───────────────────────────────────────────────────────
echo "[4/8] Cloning repository..."
if [ -d "${APP_DIR}" ]; then
  echo "  → ${APP_DIR} exists, pulling latest..."
  cd "${APP_DIR}" && git pull --ff-only
else
  git clone "${REPO}" "${APP_DIR}"
fi
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

# ── 5. Python venv + dependencies ────────────────────────────────────────
echo "[5/8] Setting up Python environment..."
su - "${APP_USER}" -c "
  cd ${APP_DIR}
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip -q
  pip install -r requirements.txt -q
  pip install slowapi -q
"

# ── 6. PostgreSQL ────────────────────────────────────────────────────────
echo "[6/8] Configuring PostgreSQL..."
systemctl enable postgresql
systemctl start postgresql

# Create database and user — set DB_PASSWORD env var before running
DB_PASSWORD="${DB_PASSWORD:?Set DB_PASSWORD environment variable before running setup}"
su - postgres -c "
  psql -c \"CREATE USER ${APP_USER} WITH PASSWORD '${DB_PASSWORD}';\" 2>/dev/null || true
  psql -c \"CREATE DATABASE opencurelabs OWNER ${APP_USER};\" 2>/dev/null || true
"

# Apply schema
su - "${APP_USER}" -c "
  PGPASSWORD='${DB_PASSWORD}' psql -h localhost -U ${APP_USER} opencurelabs < ${APP_DIR}/db/schema.sql 2>/dev/null
"

# ── 7. Caddy config ─────────────────────────────────────────────────────
echo "[7/8] Configuring Caddy..."
cat > /etc/caddy/Caddyfile << EOF
${DOMAIN} {
    reverse_proxy localhost:8787

    # Security headers
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }

    # Cache static assets
    @static path /logo.png
    header @static Cache-Control "public, max-age=86400"

    # Health check path (no caching)
    @health path /health
    header @health Cache-Control "no-cache"

    log {
        output file /var/log/caddy/opencurelabs.log
    }
}
EOF

mkdir -p /var/log/caddy
systemctl enable caddy
systemctl restart caddy

# ── 8. systemd service ──────────────────────────────────────────────────
echo "[8/8] Creating systemd service..."
cat > /etc/systemd/system/opencurelabs-dashboard.service << EOF
[Unit]
Description=OpenCure Labs Dashboard
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/.venv/bin:/usr/bin:/bin
Environment=POSTGRES_URL=postgresql://${APP_USER}:changeme_in_production@localhost/opencurelabs
ExecStart=${APP_DIR}/.venv/bin/python3 dashboard/dashboard.py --host 127.0.0.1 --port 8787
Restart=always
RestartSec=5
StandardOutput=append:/var/log/opencurelabs-dashboard.log
StandardError=append:/var/log/opencurelabs-dashboard.log

# Hardening
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${APP_DIR}/logs
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable opencurelabs-dashboard
systemctl start opencurelabs-dashboard

# ── Firewall ─────────────────────────────────────────────────────────────
echo "Configuring firewall..."
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (Caddy redirect)
ufw allow 443/tcp   # HTTPS
ufw --force enable

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Setup complete!"
echo ""
echo "  Dashboard: https://${DOMAIN}"
echo "  Health:    https://${DOMAIN}/health"
echo ""
echo "  ⚠️  IMPORTANT — Do these manually:"
echo "  1. Change the DB password in:"
echo "     /etc/systemd/system/opencurelabs-dashboard.service"
echo "     Then: systemctl daemon-reload && systemctl restart opencurelabs-dashboard"
echo ""
echo "  2. Point DNS: ${DOMAIN} A record → $(curl -4s ifconfig.me)"
echo ""
echo "  3. To sync data from your local machine:"
echo "     pg_dump -p 5433 opencurelabs | ssh root@$(curl -4s ifconfig.me) \\"
echo "       'su - ${APP_USER} -c \"PGPASSWORD=changeme_in_production psql -h localhost -U ${APP_USER} opencurelabs\"'"
echo "═══════════════════════════════════════════════════════════"
