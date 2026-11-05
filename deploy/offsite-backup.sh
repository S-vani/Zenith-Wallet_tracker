#!/usr/bin/env bash
# Off-site database backups on a free Google Drive (15 GB), encrypted on this server before they leave it. The local
# copies in ~/walletapp-backups die with the server (a Vultr node failure took both in November 2026); these don't.
# Run as the deploy user:
#
#   bash deploy/offsite-backup.sh setup     # once: connect Google Drive, create the encryption keys, test it
#   bash deploy/offsite-backup.sh check     # download the newest copy, decrypt it and check it opens
#   bash deploy/offsite-backup.sh list      # the copies on Google Drive
#   bash deploy/offsite-backup.sh fetch [N] # download the newest copy (or the one named N) for a restore
#
# How it fits: zenith-backup.sh (every 6 hours) copies each backup to BACKUP_REMOTE in .env, here the rclone "crypt"
# remote zenith-crypt, which encrypts file contents and names and stores them in gdrive:zenith-backups. Google only
# gets scope drive.file: rclone sees the files it made, nothing else in the Drive. Copies older than 30 days are
# deleted there too (the privacy policy's limit).
#
# The two encryption passwords are printed once by `setup`. Keep them OFF this server (a password manager): after
# losing the server, they plus your Google account are the only way to open the copies. On a rebuilt server, run
# `setup` again and paste the same passwords when it asks.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DRIVE="gdrive"
CRYPT="zenith-crypt"
FOLDER="zenith-backups"
ENV_FILE="$APP_DIR/.env"

if [[ -t 1 ]]; then BOLD=$'\e[1m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RED=$'\e[31m' BLUE=$'\e[34m' RESET=$'\e[0m'
else BOLD="" GREEN="" YELLOW="" RED="" BLUE="" RESET=""; fi
step() { printf '\n%s==>%s %s%s%s\n' "$BLUE" "$RESET" "$BOLD" "$*" "$RESET"; }
ok() { printf '    %sok%s  %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '    %swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }


usage() { sed -n '2,/^set -Eeuo/{/^set -Eeuo/d;s/^# \{0,1\}//;p}' "$0"; }

has_remote() { rclone listremotes | grep -qx "$1:"; }

# Whether the remote has finished Google's sign-in (a remote can exist with an empty token)
has_token() {
    rclone config dump | python3 -c '
import json, sys
sys.exit(0 if json.load(sys.stdin).get(sys.argv[1], {}).get("token") else 1)' "$1"
}

# The newest backup on the remote (names sort by time: walletdatabase-<UTC time>-<kind>.db.gz)
newest() {
    rclone lsf "$CRYPT:" --files-only --include 'walletdatabase-*.db.gz' | sort | tail -n 1
}

# Downloads one copy into a new folder and prints the file's path
download() {
    local name="$1" dir="$2"
    [[ -n "$name" ]] || die "no backups on $CRYPT: yet (run: bash $APP_DIR/deploy/zenith-backup.sh)"
    mkdir -p "$dir" && chmod 700 "$dir"
    rclone copy "$CRYPT:$name" "$dir" --quiet
    [[ -f "$dir/$name" ]] || die "couldn't download $name"
    printf '%s' "$dir/$name"
}

# Opens a downloaded copy: integrity check plus the number of accounts and trades, so you see it's the real data
inspect() {
    local file="$1" db="${1%.gz}"
    gunzip -kf "$file"
    python3 - "$db" << 'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
check = db.execute("PRAGMA integrity_check").fetchone()[0]
tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
count = lambda t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in tables else "?"
print(f"    integrity: {check}, accounts: {count('user')}, trades: {count('transactions')}")
sys.exit(0 if check == "ok" else 1)
PY
}

set_env() {
    local key="$1" value="$2" tmp
    touch "$ENV_FILE" && chmod 600 "$ENV_FILE"
    tmp="$(mktemp)"
    grep -v -E "^[[:space:]]*(export[[:space:]]+)?$key[[:space:]]*=" "$ENV_FILE" > "$tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
}

cmd_setup() {
    step "1. Google Drive"
    if has_token "$DRIVE"; then
        ok "$DRIVE is already connected"
    else
        cat << EOF
    This server has no browser, so Google's sign-in happens on your PC:
      a) On Windows, install rclone once:   winget install Rclone.Rclone   (then open a new terminal)
      b) Answer n when rclone asks to use a web browser. It then prints a command starting with
         rclone authorize "drive"  - run that on Windows, sign in with your Google account and allow access.
      c) Windows prints a token between ---> and <---. Paste it here, then answer n to "Shared Drive".
EOF
        # create only stores the settings (rclone 1.60 asks nothing there); reconnect runs the sign-in
        has_remote "$DRIVE" || rclone config create "$DRIVE" drive scope=drive.file > /dev/null
        rclone config reconnect "$DRIVE:"
        has_token "$DRIVE" || die "Google Drive wasn't connected; run setup again"
        ok "Google Drive connected"
    fi
    rclone mkdir "$DRIVE:$FOLDER"
    ok "folder $FOLDER on Google Drive"

    step "2. Encryption"
    if has_remote "$CRYPT"; then
        ok "$CRYPT already set up (its passwords are the ones you saved the first time)"
    else
        local password salt reuse=""
        read -r -p "    Restoring onto a rebuilt server with passwords you saved before? [y/N] " reuse
        if [[ "$reuse" == [yY]* ]]; then
            read -r -s -p "    Password 1: " password && echo
            read -r -s -p "    Password 2: " salt && echo
            [[ -n "$password" && -n "$salt" ]] || die "both passwords are needed"
        else
            password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
            salt="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
            cat << EOF

    ${BOLD}Save these two passwords in your password manager now (not on this server).${RESET}
    Without them nobody, including you, can open the backups.

        Zenith backups password 1:  $password
        Zenith backups password 2:  $salt

EOF
            local answer=""
            until [[ "$answer" == saved ]]; do read -r -p "    Type 'saved' once they're stored: " answer; done
            clear 2> /dev/null || true  # off the screen once saved
        fi
        # passed through stdin, so the passwords never show up in the process list
        rclone config create "$CRYPT" crypt remote="$DRIVE:$FOLDER" filename_encryption=standard \
            directory_name_encryption=true \
            password="$(printf '%s' "$password" | rclone obscure -)" \
            password2="$(printf '%s' "$salt" | rclone obscure -)" > /dev/null
        unset password salt
        ok "$CRYPT encrypts everything before it goes to Google Drive"
    fi
    chmod 600 "$(rclone config file | tail -n 1)" 2> /dev/null || true

    step "3. Backups use it"
    set_env BACKUP_REMOTE "$CRYPT:"
    ok "BACKUP_REMOTE=$CRYPT: in $ENV_FILE"
    if [[ -n "$(newest)" ]]; then
        ok "existing backups found on Google Drive: $(newest)"
    fi
    bash "$APP_DIR/deploy/zenith-backup.sh" auto | sed 's/^/    /' || die "the test backup failed (above)"

    step "4. Restore test"
    cmd_check
    cat << EOF

    Done. Every backup (every 6 hours and before each deploy) now also goes, encrypted, to Google Drive.
    Recommended: a free alert when backups stop - see docs/deploy.md, "Off-site backups".
EOF
}

cmd_check() {
    local name dir file
    name="$(newest)"
    dir="$(mktemp -d)"
    # the download holds every user's data: gone when this returns (the trap then removes itself)
    trap 'rm -rf "$dir"; trap - RETURN' RETURN
    file="$(download "$name" "$dir")"
    echo "    newest copy: $name ($(du -h "$file" | cut -f1))"
    inspect "$file" || die "that copy doesn't open cleanly"
    ok "the newest off-site copy downloads, decrypts and opens"
}

cmd_list() {
    rclone lsl "$CRYPT:" --include 'walletdatabase-*.db.gz' | sort -k2,3
}

cmd_fetch() {
    local name="${1:-$(newest)}" dir file
    dir="$HOME/walletapp-restore-$(date -u +%Y%m%dT%H%M%SZ)"
    file="$(download "$name" "$dir")"
    inspect "$file" || die "that copy doesn't open cleanly; try an older one (bash $0 list)"
    cat << EOF

    Downloaded to ${file%.gz}. To put it in place (everything written after it is lost):
      sudo systemctl stop walletapp-backend
      cd $APP_DIR && rm -f walletdatabase.db-wal walletdatabase.db-shm
      cp ${file%.gz} walletdatabase.db && chmod 600 walletdatabase.db
      sudo systemctl start walletapp-backend
    Then delete $dir (it holds every user's data).
EOF
}

case "${1:-}" in
    "" | -h | --help) usage; exit 0 ;;
esac
((EUID != 0)) || die "run it as the deploy user, not root (the backups and rclone's settings belong to deploy)"
command -v rclone > /dev/null || die "rclone isn't installed: sudo apt install -y rclone"

case "$1" in
    setup) cmd_setup ;;
    check) has_remote "$CRYPT" || die "not set up yet: bash $0 setup"; cmd_check ;;
    list) has_remote "$CRYPT" || die "not set up yet: bash $0 setup"; cmd_list ;;
    fetch) has_remote "$CRYPT" || die "not set up yet: bash $0 setup"; cmd_fetch "${2:-}" ;;
    *) usage; exit 2 ;;
esac
