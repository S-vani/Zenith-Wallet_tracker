#!/usr/bin/env bash
# Deploy the website and API on the server, as the deploy user, from ~/walletapp:
#
#   bash deploy/deploy.sh            # deploy origin/main
#   bash deploy/deploy.sh v1.4.0     # deploy a tag or commit
#
# Steps: back up the database -> check out the release -> install exact Python deps -> build the website ->
# restart the API -> wait for /health. If the health check fails, the previous commit is put back the same way.
# Only deploy commits whose CI run passed.
#
# Settings (environment): WEB_ROOT (default /var/www/html; where nginx serves the website from),
# HEALTH_URL (default http://127.0.0.1:8000/health).
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/walletapp}"
WEB_ROOT="${WEB_ROOT:-/var/www/html}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
TARGET="${1:-origin/main}"
cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "The checkout has local changes; commit or discard them first." >&2
    exit 1
fi

PREVIOUS="$(git rev-parse HEAD)"

# Check everything that can fail for setup reasons BEFORE touching anything, so a deploy never stops halfway with new
# code checked out but the old site and API still running (it happened once: /var/www/html wasn't writable).
preflight() {
    local problems=0 tool
    for tool in git uv npm rsync sqlite3 curl; do
        command -v "$tool" > /dev/null || { echo "Missing tool: $tool" >&2; problems=1; }
    done
    if ! touch "$WEB_ROOT/.deploy-write-test" 2> /dev/null; then
        echo "Can't write to $WEB_ROOT. Run once: sudo chown -R deploy:www-data $WEB_ROOT" >&2
        problems=1
    else
        rm -f "$WEB_ROOT/.deploy-write-test"
    fi
    # the API refuses to start with a short SECRET, which would only show up after the restart
    local secret_length
    secret_length="$(awk -F= '/^SECRET=/{v=substr($0,8); gsub(/"/,"",v); print length(v)}' .env 2> /dev/null)"
    if [[ -z "$secret_length" || "$secret_length" -lt 32 ]]; then
        echo "SECRET in .env must be at least 32 characters (it's ${secret_length:-missing})." >&2
        problems=1
    fi
    sudo -n true 2> /dev/null || echo "Note: sudo will ask for your password to restart the API." >&2
    return "$problems"
}

# Every step checks its own result: errexit is switched off inside a function called from `if`/`||`, which is how
# the rollback calls this.
build_and_restart() {
    git checkout --quiet --detach "$1" || return 1
    uv sync --frozen --no-dev || return 1
    (cd frontend && npm ci --no-audit --no-fund && npm run build) || return 1
    # rsync --delete so files removed from the build don't linger; -rlt (not -a) so it never tries to change the
    # owner or group of files in WEB_ROOT, which the deploy user isn't allowed to do
    rsync -rlt --delete frontend/dist/ "$WEB_ROOT/" || return 1
    sudo systemctl restart walletapp-backend || return 1
}

rollback() {
    echo "Rolling back to $PREVIOUS." >&2
    journalctl -u walletapp-backend -n 40 --no-pager >&2 || true
    if build_and_restart "$PREVIOUS" && healthy; then
        echo "Rolled back to $(git rev-parse --short HEAD). The pre-deploy database backup is in the backup folder." >&2
    else
        echo "Rollback is not healthy either; check journalctl -u walletapp-backend." >&2
    fi
    exit 1
}

healthy() {
    for _ in $(seq 1 30); do
        if curl -fsS --max-time 3 "$HEALTH_URL" > /dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

preflight || { echo "Nothing was changed. Fix the above and run the deploy again." >&2; exit 1; }
bash "$APP_DIR/deploy/zenith-backup.sh" pre-deploy
git fetch --quiet --tags origin

echo "Deploying $TARGET ($(git rev-parse --short "$TARGET")), previous $(git rev-parse --short "$PREVIOUS")"
if ! build_and_restart "$TARGET"; then
    echo "A deploy step failed." >&2
    rollback
fi

if healthy; then
    echo "Deployed $(git rev-parse --short HEAD); $HEALTH_URL is healthy."
    exit 0
fi

echo "Health check failed." >&2
rollback
