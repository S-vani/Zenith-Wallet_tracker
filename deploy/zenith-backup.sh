#!/usr/bin/env bash
# Back up the SQLite database: a consistent copy (sqlite3 .backup is safe while the API is writing, WAL included),
# gzipped, kept 30 days (the privacy policy promises backups are kept no longer), optionally copied off the server.
#
#   bash deploy/zenith-backup.sh               # nightly, from zenith-backup.timer
#   bash deploy/zenith-backup.sh pre-deploy    # deploy.sh runs this before every deploy
#
# Settings (environment or /home/deploy/walletapp/.env):
#   BACKUP_DIR     where copies go (default /home/deploy/backups/zenith)
#   BACKUP_REMOTE  optional rclone destination, e.g. "b2crypt:zenith-backups" (use an rclone "crypt" remote so the
#                  off-site copies are encrypted); unset = local copies only
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/walletapp}"
if [[ -f "$APP_DIR/.env" ]]; then
    # only the settings this script needs (never eval'd), so the secrets in .env stay out of this shell
    while IFS='=' read -r key value; do
        value="${value%\"}"; value="${value#\"}"
        [[ -z "${!key:-}" ]] && export "$key=$value"
    done < <(grep -E '^(BACKUP_DIR|BACKUP_REMOTE|DATABASE_URL)=' "$APP_DIR/.env")
fi
BACKUP_DIR="${BACKUP_DIR:-/home/deploy/backups/zenith}"
LABEL="${1:-nightly}"

# DATABASE_URL looks like sqlite+aiosqlite:///./walletdatabase.db (relative to the project) or an absolute path
DB_URL="${DATABASE_URL:-sqlite+aiosqlite:///./walletdatabase.db}"
DB_PATH="${DB_URL#sqlite+aiosqlite:///}"
[[ "$DB_PATH" == ./* ]] && DB_PATH="$APP_DIR/${DB_PATH#./}"
[[ -f "$DB_PATH" ]] || { echo "Database not found: $DB_PATH" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"  # the copies hold every user's email and trades
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUT="$BACKUP_DIR/walletdatabase-$STAMP-$LABEL.db"

sqlite3 "$DB_PATH" ".backup '$OUT'"
# a backup that can't be opened is worse than none, because it looks fine until the day it's needed
if [[ "$(sqlite3 "$OUT" 'PRAGMA integrity_check;')" != "ok" ]]; then
    echo "Integrity check failed for $OUT" >&2
    exit 1
fi
gzip -9 "$OUT"
chmod 600 "$OUT.gz"
echo "Backed up $DB_PATH to $OUT.gz"

find "$BACKUP_DIR" -name 'walletdatabase-*.db.gz' -mtime +30 -delete

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
    rclone copy "$OUT.gz" "$BACKUP_REMOTE" --quiet
    rclone delete "$BACKUP_REMOTE" --min-age 30d --quiet
    echo "Copied to $BACKUP_REMOTE"
fi
