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

build_and_restart() {
    git checkout --quiet --detach "$1"
    uv sync --frozen --no-dev
    (cd frontend && npm ci --no-audit --no-fund && npm run build)
    # rsync --delete so files removed from the build don't linger; the site is served straight from WEB_ROOT
    rsync -a --delete frontend/dist/ "$WEB_ROOT/"
    sudo systemctl restart walletapp-backend
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

bash "$APP_DIR/deploy/zenith-backup.sh" pre-deploy
git fetch --quiet --tags origin

echo "Deploying $TARGET ($(git rev-parse --short "$TARGET")), previous $(git rev-parse --short "$PREVIOUS")"
build_and_restart "$TARGET"

if healthy; then
    echo "Deployed $(git rev-parse --short HEAD); $HEALTH_URL is healthy."
    exit 0
fi

echo "Health check failed; rolling back to $PREVIOUS." >&2
journalctl -u walletapp-backend -n 40 --no-pager >&2 || true
build_and_restart "$PREVIOUS"
if healthy; then
    echo "Rolled back to $(git rev-parse --short HEAD). The pre-deploy database backup is in the backup folder." >&2
else
    echo "Rollback is not healthy either; check journalctl -u walletapp-backend." >&2
fi
exit 1
