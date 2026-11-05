#!/usr/bin/env bash
# Turns a fresh Ubuntu 24.04 server (e.g. the Vultr instance that replaced a failed node) into a Zenith server laid
# out like the old one: user `deploy`, the app in /home/deploy/walletapp, uvicorn behind nginx, certbot. Run as root:
#
#   curl -fsSLO https://raw.githubusercontent.com/S-vani/Zenith-Wallet_tracker/main/deploy/setup-server.sh
#   bash setup-server.sh
#
# Safe to run again: every step checks first and skips what's already done. It never starts the API and never
# touches a database. It writes .env and frontend/.env only when they don't exist (with a new SECRET and the public
# addresses; the API keys and email settings are left for you to fill in). The rebuild steps: docs/deploy.md.
#
#   --nginx-only   only (re)write the nginx config: HTTPS once /etc/letsencrypt has the certificate, HTTP until then
#
# Settings (environment): REPO_URL, APP_USER (deploy), NODE_MAJOR (22).
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/S-vani/Zenith-Wallet_tracker.git}"
APP_USER="${APP_USER:-deploy}"
NODE_MAJOR="${NODE_MAJOR:-22}"
SITE_HOST="zenithwalletracker.ca"
API_HOST="api.zenithwalletracker.ca"
CERT_DIR="/etc/letsencrypt/live/$SITE_HOST"

APP_HOME="/home/$APP_USER"
APP_DIR="$APP_HOME/walletapp"
NGINX_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --nginx-only) NGINX_ONLY=1 ;;
        -h | --help) sed -n '2,/^set -Eeuo/{/^set -Eeuo/d;s/^# \{0,1\}//;p}' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

if [[ -t 1 ]]; then BOLD=$'\e[1m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RED=$'\e[31m' BLUE=$'\e[34m' RESET=$'\e[0m'
else BOLD="" GREEN="" YELLOW="" RED="" BLUE="" RESET=""; fi
step() { printf '\n%s==>%s %s%s%s\n' "$BLUE" "$RESET" "$BOLD" "$*" "$RESET"; }
ok() { printf '    %sok%s  %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '    %swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

((EUID == 0)) || die "run it as root (or with sudo): sudo bash $0"
[[ -r /etc/os-release ]] && . /etc/os-release
[[ "${ID:-}" == ubuntu ]] || die "this script is written for Ubuntu (found ${PRETTY_NAME:-unknown})"
export DEBIAN_FRONTEND=noninteractive

# The repo's copy of a deploy file, from the checkout (or next to this script before the checkout exists)
repo_file() {
    local rel="$1" here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$APP_DIR/$rel" ]]; then printf '%s' "$APP_DIR/$rel"
    elif [[ -f "$here/../$rel" ]]; then printf '%s' "$here/../$rel"
    else die "can't find $rel (is the repo cloned to $APP_DIR?)"; fi
}

# install_file SRC DEST MODE: copies only when different; prints what happened
install_file() {
    if [[ -f "$2" ]] && cmp -s "$1" "$2"; then ok "$2 already up to date"
    else install -m "$3" "$1" "$2" && ok "installed $2"; fi
}

# ---------------------------------------------------------------------------------------------------- nginx
setup_nginx() {
    step "nginx"
    install_file "$(repo_file deploy/nginx/zenith-http.conf)" /etc/nginx/conf.d/zenith.conf 0644
    install_file "$(repo_file deploy/nginx/logrotate-nginx)" /etc/logrotate.d/nginx 0644
    # Ubuntu's welcome page would answer for any unknown name
    if [[ -e /etc/nginx/sites-enabled/default ]]; then rm -f /etc/nginx/sites-enabled/default && ok "removed the default site"; fi

    local site tmp
    if [[ -f "$CERT_DIR/fullchain.pem" && -f /etc/letsencrypt/options-ssl-nginx.conf ]]; then
        for site in "$SITE_HOST" "$API_HOST"; do
            install_file "$(repo_file "deploy/nginx/$site")" "/etc/nginx/sites-enabled/$site" 0644
        done
        ok "HTTPS config (certificate found in $CERT_DIR)"
    else
        # No certificate yet: plain HTTP, enough for `certbot certonly --nginx` (docs/deploy.md)
        tmp="$(mktemp)"
        cat > "$tmp" << EOF
# Temporary HTTP-only config until the certificate is in /etc/letsencrypt; setup-server.sh --nginx-only replaces it.
server {
    listen 80;
    listen [::]:80;
    server_name $SITE_HOST www.$SITE_HOST;
    root $APP_DIR/frontend/dist;
    index index.html;
    access_log /var/log/nginx/zenith.access.log zenith;
    location / { try_files \$uri /index.html; }
}
EOF
        install_file "$tmp" "/etc/nginx/sites-enabled/$SITE_HOST" 0644
        cat > "$tmp" << EOF
# Temporary HTTP-only config until the certificate is in /etc/letsencrypt; setup-server.sh --nginx-only replaces it.
server {
    listen 80;
    listen [::]:80;
    server_name $API_HOST;
    access_log /var/log/nginx/zenith.access.log zenith;
    client_max_body_size 3m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        install_file "$tmp" "/etc/nginx/sites-enabled/$API_HOST" 0644
        rm -f "$tmp"
        warn "no certificate in $CERT_DIR yet: HTTP only for now (get one with certbot, then --nginx-only)"
    fi
    nginx -t 2>&1 | sed 's/^/    /' || die "nginx rejected the config (above); fix it and run this again"
    systemctl enable --now nginx > /dev/null
    systemctl reload nginx
    ok "nginx reloaded"
}

if ((NGINX_ONLY)); then
    setup_nginx
    exit 0
fi

# ---------------------------------------------------------------------------------------------------- packages
step "Packages"
apt-get update -q
apt-get install -y -q nginx certbot python3-certbot-nginx git curl ca-certificates gnupg sqlite3 gzip rsync rclone \
    unattended-upgrades util-linux > /dev/null
ok "nginx, certbot, git, sqlite3, rclone and friends"
# security updates install themselves (Ubuntu's default, made explicit)
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
    > /etc/apt/apt.conf.d/20auto-upgrades
ok "automatic security updates on"

# Node: Vite 8 needs Node 20.19+ / 22.12+, and Ubuntu's own nodejs is older. NodeSource's signed apt repo.
if command -v node > /dev/null && [[ "$(node -p 'process.versions.node.split(".")[0]')" -ge "$NODE_MAJOR" ]]; then
    ok "node $(node -v)"
else
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -q && apt-get install -y -q nodejs > /dev/null
    ok "node $(node -v)"
fi

# uv into /usr/local/bin so it's on PATH for every user and for deploy.sh (the installer otherwise picks ~/.local/bin)
if command -v uv > /dev/null; then
    ok "uv $(uv --version | awk '{print $2}')"
else
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh > /dev/null
    ok "uv $(/usr/local/bin/uv --version | awk '{print $2}')"
fi

# ---------------------------------------------------------------------------------------------------- swap
# A 1 GB server runs out of memory during npm ci + the Vite build without swap
mem_mb="$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)"
if ((mem_mb < 3000)) && ! swapon --show | grep -q .; then
    step "Swap (only ${mem_mb} MB of memory)"
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile > /dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "2 GB swap file"
fi

# ---------------------------------------------------------------------------------------------------- firewall
# Vultr's Ubuntu images turn ufw on with only SSH allowed. Port 8000 stays closed: uvicorn listens on 127.0.0.1.
step "Firewall (ports 80 and 443)"
if command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
    ufw allow OpenSSH > /dev/null
    ufw allow 80/tcp > /dev/null
    ufw allow 443/tcp > /dev/null
    ok "ufw allows SSH, 80 and 443"
else
    ok "ufw isn't on; nothing to open here (check the provider's firewall allows 80 and 443)"
fi

# ---------------------------------------------------------------------------------------------------- user
step "User $APP_USER"
if id "$APP_USER" > /dev/null 2>&1; then
    ok "$APP_USER exists"
else
    adduser --disabled-password --gecos "Zenith deploy" "$APP_USER" > /dev/null
    ok "created $APP_USER"
fi
usermod -aG sudo "$APP_USER"
# Same SSH keys as the account running this, so `ssh deploy@<ip>` works with a key you already use
key_source="/root/.ssh/authorized_keys"
[[ -n "${SUDO_USER:-}" ]] && key_source="/home/$SUDO_USER/.ssh/authorized_keys"
if [[ -s "$key_source" && ! -s "$APP_HOME/.ssh/authorized_keys" ]]; then
    install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$APP_HOME/.ssh"
    install -m 600 -o "$APP_USER" -g "$APP_USER" "$key_source" "$APP_HOME/.ssh/authorized_keys"
    ok "copied the SSH keys from $key_source"
fi
# deploy.sh uses sudo for systemctl and nginx, and sudo asks for this password (it's also the SSH password)
if [[ "$(passwd -S "$APP_USER" | awk '{print $2}')" != P ]]; then
    echo "    Choose a password for $APP_USER (SSH login, and sudo during deploys):"
    passwd "$APP_USER"
fi
# nginx (www-data) serves $APP_DIR/frontend/dist, so it must be able to pass through the home folder. 711 lets it
# through without letting it list anything; Ubuntu 24.04 creates homes as 750.
chmod 711 "$APP_HOME"
ok "nginx can reach $APP_DIR/frontend/dist"

# ---------------------------------------------------------------------------------------------------- code
step "Code in $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
    ok "already cloned ($(sudo -u "$APP_USER" git -C "$APP_DIR" log -1 --format='%h %s'))"
else
    sudo -u "$APP_USER" git clone -q "$REPO_URL" "$APP_DIR"
    ok "cloned $REPO_URL"
fi

# ---------------------------------------------------------------------------------------------------- .env
# Only when missing: an existing .env is never touched. A new SECRET signs everyone out, which a lost server does anyway.
step "Settings (.env)"
if [[ -f "$APP_DIR/.env" ]]; then
    ok "$APP_DIR/.env already exists (left as it is)"
else
    secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    cat > "$APP_DIR/.env" << EOF
SECRET=$secret
FRONTEND_URL=https://$SITE_HOST
BACKEND_URL=https://$API_HOST
# Fill these in (full list: CLAUDE.md "Environment"), then deploy:
# TwelveData (stock search) and CoinGecko demo keys
API_KEY=
API_KEY_COINEGECKO=
# Email for verification and password-reset links: SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/EMAIL_FROM, or
GMAIL_USER=
GMAIL_PASS=
# Google sign-in (the button is hidden without them)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
EOF
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env" && chmod 600 "$APP_DIR/.env"
    ok "wrote $APP_DIR/.env with a new SECRET; fill in the empty keys"
fi
if [[ -f "$APP_DIR/frontend/.env" ]]; then
    ok "$APP_DIR/frontend/.env already exists (left as it is)"
else
    echo "VITE_BACKEND_URL=https://$API_HOST" > "$APP_DIR/frontend/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/frontend/.env"
    ok "wrote $APP_DIR/frontend/.env (the website's API address)"
fi

# ---------------------------------------------------------------------------------------------------- systemd
step "Services"
install_file "$(repo_file deploy/walletapp-backend.service)" /etc/systemd/system/walletapp-backend.service 0644
install -d -m 0755 /etc/systemd/journald.conf.d
if ! cmp -s "$(repo_file deploy/journald-zenith.conf)" /etc/systemd/journald.conf.d/zenith.conf 2> /dev/null; then
    install -m 0644 "$(repo_file deploy/journald-zenith.conf)" /etc/systemd/journald.conf.d/zenith.conf
    systemctl restart systemd-journald
    ok "journal kept for 14 days"
else
    ok "journal already kept for 14 days"
fi
systemctl daemon-reload
# enabled for boot, but not started: the first deploy builds and starts it (and a restored database goes in first)
systemctl enable walletapp-backend > /dev/null 2>&1
ok "walletapp-backend enabled (starts with the first deploy)"

setup_nginx

step "Done"
cat << EOF
    Server is ready. Next (docs/deploy.md, "Rebuilding the server"):
      1. nano $APP_DIR/.env              fill in the API keys and email settings
      2. certbot certonly --nginx -d $SITE_HOST -d www.$SITE_HOST -d $API_HOST
      3. bash $0 --nginx-only            switches nginx to HTTPS
      4. su - $APP_USER   (then, as $APP_USER: bash ~/walletapp/deploy/deploy.sh --force --install-backups)
      5. as $APP_USER: bash ~/walletapp/deploy/offsite-backup.sh setup   (encrypted copies on Google Drive)
EOF
