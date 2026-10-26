#!/usr/bin/env bash
# Back up the SQLite database: a consistent copy taken while the API keeps running (SQLite's online backup, WAL
# included), integrity-checked, gzipped, optionally copied off the server.
#
#   bash deploy/zenith-backup.sh               # nightly, from zenith-backup.timer (deploy.sh --install-backups)
#   bash deploy/zenith-backup.sh pre-deploy    # deploy.sh runs this before every deploy
#
# Uses the sqlite3 command if it's installed, otherwise Python's sqlite3 module (the project's .venv, or python3).
# Keeps the newest 30 copies of each kind and nothing older than 30 days (the privacy policy promises no longer).
#
# Settings (environment, or .env in the project):
#   BACKUP_DIR     where copies go (default ~/walletapp-backups)
#   BACKUP_REMOTE  optional rclone destination, e.g. "b2crypt:zenith-backups" (use an rclone "crypt" remote so the
#                  off-site copies are encrypted); unset = local copies only
set -Eeuo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LABEL="${1:-nightly}"
KEEP="${BACKUP_KEEP:-30}"

venv_python() {
    local p
    for p in "$APP_DIR/.venv/bin/python" "$APP_DIR/.venv/Scripts/python.exe"; do
        [[ -x "$p" ]] && { printf '%s' "$p"; return 0; }
    done
    return 1
}

# A setting from .env, parsed by python-dotenv like the app does; a plain KEY=value fallback without .venv. Only
# the keys asked for are read, so the secrets in .env never enter this shell.
env_value() {
    local key="$1" file="$APP_DIR/.env" py line
    [[ -f "$file" ]] || return 0
    if py="$(venv_python)" && "$py" -c 'import dotenv' 2> /dev/null; then
        "$py" -c 'import sys
from dotenv import dotenv_values
print(dotenv_values(sys.argv[1]).get(sys.argv[2]) or "", end="")' "$file" "$key"
        return 0
    fi
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$file" | tail -n 1 | tr -d '\r')" || true
    line="${line#*=}"
    line="${line#"${line%%[![:space:]]*}"}"
    if [[ "$line" =~ ^\"(.*)\"[[:space:]]*(#.*)?$ || "$line" =~ ^\'(.*)\'[[:space:]]*(#.*)?$ ]]; then
        line="${BASH_REMATCH[1]}"
    else
        line="${line%%[[:space:]]#*}"
        line="${line%"${line##*[![:space:]]}"}"
    fi
    printf '%s' "$line"
}

BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-${HOME:-$(dirname "$APP_DIR")}/walletapp-backups}"
BACKUP_REMOTE="${BACKUP_REMOTE:-$(env_value BACKUP_REMOTE)}"

# DATABASE_URL looks like sqlite+aiosqlite:///./walletdatabase.db (relative to the project, as backend/db/database.py
# anchors it) or sqlite+aiosqlite:////an/absolute/path.db
DB_URL="${DATABASE_URL:-$(env_value DATABASE_URL)}"
DB_URL="${DB_URL:-sqlite+aiosqlite:///./walletdatabase.db}"
[[ "$DB_URL" == sqlite*:///* ]] || { echo "DATABASE_URL isn't SQLite; nothing to back up here" >&2; exit 1; }
DB_PATH="${DB_URL#*:///}"
DB_PATH="${DB_PATH%%\?*}"
DB_PATH="${DB_PATH#./}"
[[ "$DB_PATH" == /* || "$DB_PATH" == [A-Za-z]:* ]] || DB_PATH="$APP_DIR/$DB_PATH"
[[ -f "$DB_PATH" ]] || { echo "Database not found: $DB_PATH" >&2; exit 1; }

umask 077  # the copies hold every user's email and trades
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUT="$BACKUP_DIR/walletdatabase-$STAMP-$LABEL.db"
trap 'rm -f "$OUT"' ERR

if command -v sqlite3 > /dev/null; then
    sqlite3 "$DB_PATH" ".timeout 30000" ".backup '$OUT'"
    CHECK="$(sqlite3 "$OUT" 'PRAGMA integrity_check;')"
else
    # the first Python that can import sqlite3 (`python3` can be a stub that only prints an install hint)
    PY=""
    for candidate in "$(venv_python)" "$(command -v python3)" "$(command -v python)"; do
        if [[ -n "$candidate" ]] && "$candidate" -c 'import sqlite3' > /dev/null 2>&1; then
            PY="$candidate"
            break
        fi
    done
    [[ -n "$PY" ]] || { echo "Neither sqlite3 nor Python with sqlite3 is installed; can't back up" >&2; exit 1; }
    CHECK="$("$PY" - "$DB_PATH" "$OUT" << 'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=30)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)  # SQLite's online backup API: a consistent snapshot even while the API writes
src.close()
print(dst.execute("PRAGMA integrity_check").fetchone()[0])
dst.close()
PY
)"
fi
# a backup that can't be opened is worse than none, because it looks fine until the day it's needed
if [[ "$CHECK" != "ok" ]]; then
    echo "Integrity check failed for $OUT: $CHECK" >&2
    rm -f "$OUT"
    exit 1
fi
gzip -9 "$OUT"
chmod 600 "$OUT.gz"
echo "Backed up $DB_PATH to $OUT.gz"

find "$BACKUP_DIR" -name 'walletdatabase-*.db.gz' -mtime +30 -delete
# newest KEEP of this kind (deploys can happen several times a day)
ls -1t "$BACKUP_DIR"/walletdatabase-*-"$LABEL".db.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old"
done

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
    rclone copy "$OUT.gz" "$BACKUP_REMOTE" --quiet
    rclone delete "$BACKUP_REMOTE" --min-age 30d --quiet
    echo "Copied to $BACKUP_REMOTE"
fi
