#!/usr/bin/env bash
#
# Simple installer for MikroTik 2FA Telegram-only bot (RouterOS API-only)
#
# What it does:
# - installs system deps (Debian/Ubuntu via apt)
# - creates venv and installs pip deps
# - interactively asks for Telegram/MikroTik settings and writes .env
# - creates and enables a systemd service for autostart
#

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log_error "Run as root: sudo bash install.sh"
    exit 1
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

pm_update() {
  if have_cmd apt-get; then
    DEBIAN_FRONTEND=noninteractive apt-get update -y
    return 0
  fi
  log_error "Unsupported package manager. This script currently supports apt-get only."
  exit 1
}

pm_install() {
  if have_cmd apt-get; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
    return 0
  fi
  log_error "Unsupported package manager. This script currently supports apt-get only."
  exit 1
}

ensure_python() {
  log_step "Checking Python..."
  if ! have_cmd python3; then
    pm_update
    pm_install python3
  fi
  local v
  v="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null || true)"
  if [[ -z "${v}" ]]; then
    log_error "Failed to detect python3 version"
    exit 1
  fi
  if [[ "$(printf '%s\n' "3.11" "${v}" | sort -V | head -n1)" != "3.11" ]]; then
    log_error "Python 3.11+ required. Installed: ${v}"
    exit 1
  fi
  log_info "Python ${v} OK"
}

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/mikrotik-2fa-telegram-only}"
SERVICE_NAME="mikrotik-2fa-telegram-only"
RUN_USER="${RUN_USER:-mikrotik-2fa}"
CREATE_USER="${CREATE_USER:-true}"

ensure_system_user() {
  log_step "Creating system user (${RUN_USER})..."
  if [[ "${CREATE_USER}" != "true" ]]; then
    RUN_USER="$(logname 2>/dev/null || echo root)"
    log_warn "CREATE_USER=false → will run as: ${RUN_USER}"
    return 0
  fi
  if id "${RUN_USER}" >/dev/null 2>&1; then
    log_info "User ${RUN_USER} already exists"
    return 0
  fi
  if useradd -r -s /usr/sbin/nologin -d "${INSTALL_DIR}" -m "${RUN_USER}" 2>/dev/null; then
    log_info "User ${RUN_USER} created"
  else
    RUN_USER="$(logname 2>/dev/null || echo root)"
    log_warn "Failed to create user. Will run as: ${RUN_USER}"
  fi
}

install_system_deps() {
  log_step "Installing system dependencies..."
  pm_update
  pm_install ca-certificates python3-venv python3-pip
  log_info "System deps installed"
}

copy_project() {
  log_step "Deploying project to ${INSTALL_DIR}..."
  mkdir -p "${INSTALL_DIR}"
  # Copy everything except venv to INSTALL_DIR (works without rsync).
  # This avoids service user being blocked by /root permissions.
  rm -rf "${INSTALL_DIR}/venv" "${INSTALL_DIR}/mikrotik_2fa_bot" || true
  tar -C "${SRC_DIR}" -cf - --exclude='./venv' . | tar -C "${INSTALL_DIR}" -xf -
  log_info "Project deployed to ${INSTALL_DIR}"
}

setup_venv() {
  log_step "Setting up Python venv + dependencies..."
  cd "${INSTALL_DIR}"
  if [[ ! -d "venv" ]]; then
    python3 -m venv venv
  fi
  ./venv/bin/pip install --upgrade pip setuptools wheel
  ./venv/bin/pip install -r requirements.txt
  log_info "Python deps installed"
}

prompt_env() {
  log_step "Interactive configuration (.env)..."
  cd "${INSTALL_DIR}"

  local token admin_chat admin_ids admin_usernames host user pass port use_ssl

  echo ""
  echo "Telegram:"
  while true; do
    read -r -p "  Bot token (TELEGRAM_BOT_TOKEN) [required]: " token
    # remove ASCII control chars, trim spaces
    token="$(printf '%s' "${token}" | LC_ALL=C tr -d '[:cntrl:]' | xargs || true)"
    # extract first valid-looking token if user pasted extra junk
    token="$(printf '%s' "${token}" | sed -nE 's/.*([0-9]{5,20}:[A-Za-z0-9_-]{20,}).*/\\1/p')"
    if [[ -z "${token}" ]]; then
      log_warn "Token is empty or invalid. Paste token from BotFather like: 123456:ABCDEF..."
      continue
    fi
    if [[ "${token}" =~ ^[0-9]{5,20}:[A-Za-z0-9_-]{20,}$ ]]; then
      break
    fi
    log_warn "Token format looks invalid. Try again."
  done

  read -r -p "  Admin chat id (ADMIN_CHAT_ID) [optional, press Enter to skip]: " admin_chat
  read -r -p "  Admin user id(s) (ADMIN_TELEGRAM_IDS) [recommended, comma-separated, optional]: " admin_ids
  read -r -p "  Admin username(s) (ADMIN_USERNAMES) [fallback, without @, comma-separated, optional]: " admin_usernames
  if [[ -z "${admin_chat}" && -z "${admin_ids}" && -z "${admin_usernames}" ]]; then
    log_warn "No admin restriction configured. Admin commands will be blocked until you set ADMIN_CHAT_ID or ADMIN_TELEGRAM_IDS or ADMIN_USERNAMES."
  fi

  echo ""
  echo "MikroTik RouterOS API:"
  read -r -p "  Host/IP (MIKROTIK_HOST) [required]: " host
  while [[ -z "${host}" ]]; do
    read -r -p "  MIKROTIK_HOST cannot be empty. Enter host/ip: " host
  done
  read -r -p "  Username (MIKROTIK_USERNAME) [required]: " user
  while [[ -z "${user}" ]]; do
    read -r -p "  MIKROTIK_USERNAME cannot be empty. Enter username: " user
  done
  read -r -s -p "  Password (MIKROTIK_PASSWORD) [required]: " pass
  echo ""
  while [[ -z "${pass}" ]]; do
    read -r -s -p "  Password cannot be empty. Enter MIKROTIK_PASSWORD: " pass
    echo ""
  done

  read -r -p "  Port (MIKROTIK_PORT) [8728]: " port
  port="${port:-8728}"
  read -r -p "  Use SSL? (MIKROTIK_USE_SSL) [false/true] [false]: " use_ssl
  use_ssl="${use_ssl:-false}"

  mkdir -p "${INSTALL_DIR}/data"
  cat > "${INSTALL_DIR}/.env" <<EOF
TELEGRAM_BOT_TOKEN=${token}
ADMIN_CHAT_ID=${admin_chat}
ADMIN_TELEGRAM_IDS=${admin_ids}
ADMIN_USERNAMES=${admin_usernames}

DATABASE_URL=sqlite:///./data/app.db

MIKROTIK_HOST=${host}
MIKROTIK_PORT=${port}
MIKROTIK_USE_SSL=${use_ssl}
MIKROTIK_USERNAME=${user}
MIKROTIK_PASSWORD=${pass}

POLL_INTERVAL_SECONDS=5
REQUIRE_CONFIRMATION=true
CONFIRMATION_TIMEOUT_SECONDS=300
SESSION_DURATION_HOURS=24
SESSION_SOURCE=user_manager

FIREWALL_COMMENT_PREFIX=2FA
EOF

  chmod 600 "${INSTALL_DIR}/.env" || true
  chown "${RUN_USER}:${RUN_USER}" "${INSTALL_DIR}/.env" 2>/dev/null || true
  log_info ".env written to ${INSTALL_DIR}/.env"
}

write_systemd() {
  log_step "Creating systemd service..."
  if ! have_cmd systemctl; then
    log_error "systemd is not available (systemctl not found)."
    exit 1
  fi

  local svc="/etc/systemd/system/${SERVICE_NAME}.service"
  cat > "${svc}" <<EOF
[Unit]
Description=MikroTik 2FA Telegram-only Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/python3 -m mikrotik_2fa_bot
Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}/data ${INSTALL_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  log_info "Service enabled and started: ${SERVICE_NAME}.service"
  log_info "Check logs: journalctl -u ${SERVICE_NAME}.service -f"
}

fix_permissions() {
  log_step "Fixing permissions..."
  chown -R "${RUN_USER}:${RUN_USER}" "${INSTALL_DIR}" 2>/dev/null || true
  log_info "Permissions updated"
}

main() {
  need_root
  ensure_python
  install_system_deps
  ensure_system_user
  copy_project
  setup_venv
  prompt_env
  fix_permissions
  write_systemd

  echo ""
  log_info "Done."
  log_info "Admin config:"
  log_info "  INSTALL_DIR=${INSTALL_DIR}"
  log_info "  ADMIN_CHAT_ID=$(grep -E '^ADMIN_CHAT_ID=' "${INSTALL_DIR}/.env" | cut -d= -f2-)"
  log_info "  ADMIN_TELEGRAM_IDS=$(grep -E '^ADMIN_TELEGRAM_IDS=' "${INSTALL_DIR}/.env" | cut -d= -f2-)"
  log_info "  ADMIN_USERNAMES=$(grep -E '^ADMIN_USERNAMES=' "${INSTALL_DIR}/.env" | cut -d= -f2-)"
}

main "$@"

