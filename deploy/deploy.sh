#!/usr/bin/env bash
# One-command deploy of the Zenith website + API, on the server as the deploy user:
#
#   bash ~/walletapp/deploy/deploy.sh          (or ./deploy.sh from the repo root)
#
# What it does, in order (details in docs/deploy.md):
#   1. preflight: tools, clean checkout, SECRET in .env, free disk space, sudo (asks for the password once)
#   2. git fetch origin/main; stops if there's nothing new. If this script changed upstream it runs the new version.
#   3. backs up the database (consistent SQLite copy + integrity check, deploy/zenith-backup.sh)
#   4. git merge --ff-only origin/main
#   5. uv sync --frozen, npm ci, website built into frontend/dist-next (the live frontend/dist is untouched)
#   6. restarts walletapp-backend and waits for /health on 127.0.0.1:8000
#   7. swaps the new website in (dist -> dist-prev, dist-next -> dist) and checks the public URLs
# Any failure from step 4 on rolls everything back to the commit that was running (see rollback()).
#
# Flags:
#   --force                    redeploy even if nothing changed; also allows local changes in the checkout
#   --dry-run                  print what would happen; changes nothing (it does git fetch, to see what's new)
#   --status                   show the deployed commit, the service and health, then exit
#   --setup-nginx              one-time: API upload limit 64k -> 3m (CSV import), nginx -t, reload (then deploys)
#   --install-backups          one-time: install the nightly backup timer (then deploys)
#   --restore-db-on-rollback   let a rollback also restore the pre-deploy database copy (see rollback())
#
# Settings (environment): SERVICE, DEPLOY_BRANCH, LOCAL_API_URL, PUBLIC_API_URL, PUBLIC_SITE_URL, HEALTH_TIMEOUT,
# MIN_FREE_MB, BACKUP_DIR, NGINX_SITES_DIR. Defaults below.
set -Eeuo pipefail

SERVICE="${SERVICE:-walletapp-backend}"
BRANCH="${DEPLOY_BRANCH:-main}"
LOCAL_API_URL="${LOCAL_API_URL:-http://127.0.0.1:8000}"
PUBLIC_API_URL="${PUBLIC_API_URL:-https://api.zenithwalletracker.ca}"
PUBLIC_SITE_URL="${PUBLIC_SITE_URL:-https://zenithwalletracker.ca}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-30}"
MIN_FREE_MB="${MIN_FREE_MB:-1024}"
NGINX_SITES_DIR="${NGINX_SITES_DIR:-/etc/nginx/sites-enabled}"
# CSV imports send up to 2 MB; the API site used to allow 64k
NGINX_BODY_LIMIT="3m"

# The repo this script belongs to. ZENITH_APP_DIR is set when the script re-runs a newer copy of itself from a temp
# file (see maybe_reexec), and the fallback covers `bash <(git show origin/main:deploy/deploy.sh)`.
if [[ -n "${ZENITH_APP_DIR:-}" ]]; then
    APP_DIR="$ZENITH_APP_DIR"
elif [[ -f "${BASH_SOURCE[0]}" ]]; then
    APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
    APP_DIR="/home/deploy/walletapp"
fi
FRONTEND="$APP_DIR/frontend"
STATE_DIR="$APP_DIR/.deploy"  # gitignored: last deployed commit, history, lock

ORIG_ARGS=("$@")
FORCE=0 DRY_RUN=0 STATUS=0 SETUP_NGINX=0 INSTALL_BACKUPS=0 RESTORE_DB_ON_ROLLBACK=0

# ---------------------------------------------------------------------------------------------------- output helpers
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' YELLOW=$'\e[33m' BLUE=$'\e[34m' RESET=$'\e[0m'
else
    BOLD="" DIM="" RED="" GREEN="" YELLOW="" BLUE="" RESET=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$BLUE" "$RESET" "$BOLD" "$*" "$RESET"; }
info() { printf '    %s\n' "$*"; }
ok() { printf '    %sok%s  %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '    %swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
err() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; }
die() { FAIL_REASON="$*"; err "$*"; exit 1; }
short() { git -C "$APP_DIR" rev-parse --short "$1" 2> /dev/null || printf '%s' "${1:0:7}"; }
# run CMD...: runs it, or in --dry-run only prints it
run() {
    if ((DRY_RUN)); then
        printf '    %s[dry-run]%s' "$DIM" "$RESET"
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}
dry() { if ((DRY_RUN)); then printf '    %s[dry-run]%s %s\n' "$DIM" "$RESET" "$*"; fi; }

usage() { sed -n '2,/^set -Eeuo/{/^set -Eeuo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; }

# ---------------------------------------------------------------------------------------------------- small helpers
venv_python() {
    local p
    for p in "$APP_DIR/.venv/bin/python" "$APP_DIR/.venv/Scripts/python.exe"; do
        [[ -x "$p" ]] && { printf '%s' "$p"; return 0; }
    done
    return 1
}
any_python() { venv_python || command -v python3 || command -v python; }

# env_value KEY: KEY's value in .env, parsed by python-dotenv like the app does (quotes, `export`, comments). Before
# .venv exists, a plain fallback: last KEY=..., surrounding quotes or a trailing " # comment" removed.
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

# The database file, resolved like backend/db/database.py (relative paths are anchored to the project root)
db_path() {
    local url path
    url="${DATABASE_URL:-$(env_value DATABASE_URL)}"
    url="${url:-sqlite+aiosqlite:///./walletdatabase.db}"
    [[ "$url" == sqlite*:///* ]] || return 1
    path="${url#*:///}"
    path="${path%%\?*}"
    path="${path#./}"
    [[ "$path" == /* || "$path" == [A-Za-z]:* ]] || path="$APP_DIR/$path"
    printf '%s' "$path"
}

backup_dir() {
    local dir="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
    printf '%s' "${dir:-${HOME:-$(dirname "$APP_DIR")}/walletapp-backups}"
}

# A fingerprint of the database schema (tables, columns, indexes). Startup migrations (create_all for new tables,
# ADDED_COLUMNS for new columns) change it; ordinary user writes don't.
schema_fingerprint() {
    local db py
    db="$(db_path)" && [[ -f "$db" ]] && py="$(any_python)" || { printf 'unknown'; return 0; }
    "$py" - "$db" 2> /dev/null << 'PY' || printf 'unknown'
import hashlib, sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=10)
rows = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
print(hashlib.sha256(repr(rows).encode()).hexdigest(), end="")
PY
}

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-5}" "$1" 2> /dev/null || true; }

# api_ok BASE: /health answers 200. Commits before 9fcc567 have no /health (404), so /auth/providers counts then.
api_ok() {
    local code
    code="$(http_code "$1/health" "${2:-5}")"
    [[ "$code" == 200 ]] && return 0
    [[ "$code" == 404 && "$(http_code "$1/auth/providers" "${2:-5}")" == 200 ]]
}

# Waits up to HEALTH_TIMEOUT seconds for the local API, then checks it's still up a few seconds later (a backend that
# crashes right after startup would otherwise pass once and then crash-loop).
wait_healthy() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT))
    while ((SECONDS < deadline)); do
        if api_ok "$LOCAL_API_URL"; then
            sleep 3
            api_ok "$LOCAL_API_URL" && return 0
        fi
        sleep 1
    done
    return 1
}

show_journal() {
    command -v journalctl > /dev/null || return 0
    info "Last API log lines:"
    { journalctl -u "$SERVICE" -n 30 --no-pager 2> /dev/null || sudo -n journalctl -u "$SERVICE" -n 30 --no-pager; } |
        sed 's/^/      /' >&2 || true
}

entry_script() { grep -oE 'src="/assets/[^"]+\.js"' "$1" 2> /dev/null | head -n 1 || true; }

# ---------------------------------------------------------------------------------------------------- status
show_status() {
    cd "$APP_DIR"
    step "Zenith deploy status ($APP_DIR)"
    git fetch --quiet origin "$BRANCH" 2> /dev/null || warn "git fetch failed; origin/$BRANCH may be out of date"
    info "Checkout:      $(git log -1 --format='%h %s (%cr)')  [$(git symbolic-ref -q --short HEAD || echo detached)]"
    local deployed=""
    [[ -f "$STATE_DIR/deployed" ]] && deployed="$(cat "$STATE_DIR/deployed")"
    info "Last deployed: ${deployed:+$(git log -1 --format='%h %s (%cr)' "$deployed" 2> /dev/null || echo "$deployed")}${deployed:-unknown (no deploy with this script yet)}"
    local behind
    behind="$(git rev-list --count "HEAD..origin/$BRANCH" 2> /dev/null || echo '?')"
    info "origin/$BRANCH:   $(git log -1 --format='%h %s (%cr)' "origin/$BRANCH")  ($behind new commit(s))"
    [[ -n "$(git status --porcelain --untracked-files=no)" ]] && warn "the checkout has local changes"

    if command -v systemctl > /dev/null; then
        info "Service:       $SERVICE is $(systemctl is-active "$SERVICE" 2> /dev/null || true)," \
            "since $(systemctl show -p ActiveEnterTimestamp --value "$SERVICE" 2> /dev/null || echo '?')"
        # deploy/walletapp-backend.service is a reference copy; the installed unit is never overwritten
        if [[ -f deploy/walletapp-backend.service ]] &&
            ! diff -q <(systemctl cat "$SERVICE" 2> /dev/null | grep -vE '^[[:space:]]*(#|$)') \
                <(grep -vE '^[[:space:]]*(#|$)' deploy/walletapp-backend.service) > /dev/null 2>&1; then
            info "               (installed unit differs from deploy/walletapp-backend.service; see docs/deploy.md)"
        fi
    fi
    if api_ok "$LOCAL_API_URL"; then ok "local API $LOCAL_API_URL"; else warn "local API $LOCAL_API_URL is not healthy"; fi
    if api_ok "$PUBLIC_API_URL" 10; then ok "public API $PUBLIC_API_URL"; else warn "public API $PUBLIC_API_URL is not healthy"; fi
    local code
    code="$(http_code "$PUBLIC_SITE_URL/" 10)"
    if [[ "$code" == 200 ]]; then ok "website $PUBLIC_SITE_URL"; else warn "website $PUBLIC_SITE_URL answered $code"; fi
    if [[ -f "$FRONTEND/dist/index.html" ]]; then
        info "Website build: frontend/dist from $(date -r "$FRONTEND/dist/index.html" '+%Y-%m-%d %H:%M')" \
            "$([[ -d "$FRONTEND/dist-prev" ]] && echo '(previous build kept in dist-prev)')"
    fi
    local dir latest
    dir="$(backup_dir)"
    latest="$(ls -1t "$dir"/walletdatabase-*.db.gz 2> /dev/null | head -n 1 || true)"
    info "Latest backup: ${latest:-none in $dir}"
    if [[ -f "$STATE_DIR/history" ]]; then
        info "Recent deploys:"
        tail -n 5 "$STATE_DIR/history" | sed 's/^/      /'
    fi
}

# ---------------------------------------------------------------------------------------------------- preflight
preflight() {
    step "Preflight checks"
    local problems=0 tool
    for tool in git uv npm node curl gzip; do
        command -v "$tool" > /dev/null || { err "missing tool: $tool"; problems=1; }
    done
    if command -v sqlite3 > /dev/null; then
        ok "tools (git, uv, npm, curl, sqlite3)"
    else
        ok "tools (git, uv, npm, curl; no sqlite3, so backups use Python's sqlite3 module)"
    fi

    git rev-parse --git-dir > /dev/null 2>&1 || die "$APP_DIR is not a git checkout"
    git remote get-url origin > /dev/null 2>&1 || die "the checkout has no 'origin' remote"

    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        if ((FORCE)); then
            warn "the checkout has local changes (continuing because of --force):"
            git status --short --untracked-files=no | sed 's/^/      /' >&2
        else
            err "the checkout has local changes; commit or discard them (git status), or pass --force:"
            git status --short --untracked-files=no | sed 's/^/      /' >&2
            problems=1
        fi
    else
        ok "clean checkout ($(git log -1 --format='%h %s'))"
    fi

    # The API refuses to start with a SECRET under 32 characters, which would otherwise only show after the restart.
    # Parsed like python-dotenv (quotes don't count), which is how the app reads it.
    if [[ ! -f "$APP_DIR/.env" ]]; then
        err "$APP_DIR/.env is missing"
        problems=1
    else
        local secret
        secret="$(env_value SECRET)"
        if ((${#secret} < 32)); then
            err "SECRET in .env must be at least 32 characters (it's ${#secret}). Generate one with:" \
                "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\" (changing it signs everyone out)"
            problems=1
        else
            ok "SECRET is set (${#secret} characters)"
        fi
        unset secret
    fi

    local free_mb
    free_mb="$(df -Pk "$APP_DIR" | awk 'NR == 2 {print int($4 / 1024)}')"
    if [[ -n "$free_mb" ]] && ((free_mb < MIN_FREE_MB)); then
        err "only ${free_mb} MB free on the disk with $APP_DIR; need ${MIN_FREE_MB} MB (node_modules + a build + a backup)"
        problems=1
    else
        ok "${free_mb:-?} MB free on disk"
    fi

    if command -v systemctl > /dev/null; then
        if systemctl cat "$SERVICE" > /dev/null 2>&1; then
            ok "service $SERVICE is installed ($(systemctl is-active "$SERVICE" 2> /dev/null || true))"
        else
            err "systemd service $SERVICE not found; install it first (docs/deploy.md)"
            problems=1
        fi
    else
        warn "no systemctl on this machine"
    fi

    ((problems == 0)) || die "Nothing was changed. Fix the above and run the deploy again."

    if ((DRY_RUN)); then
        dry "sudo -v  (asks for your password once, for systemctl and nginx)"
    elif ! sudo -n true 2> /dev/null; then
        info "sudo is needed to restart the API; enter your password once:"
        sudo -v || die "sudo failed; nothing was changed"
    fi
}

# Keeps the sudo timestamp fresh during a long build so the password is asked only once
start_sudo_keepalive() {
    ((DRY_RUN)) && return 0
    (while kill -0 "$$" 2> /dev/null; do
        sudo -n -v 2> /dev/null || true
        sleep 50
    done) > /dev/null 2>&1 &
    SUDO_KEEPALIVE_PID=$!
}

acquire_lock() {
    mkdir -p "$STATE_DIR"
    # after a re-exec the lock is still held on the inherited fd 9
    [[ -n "${ZENITH_DEPLOY_REEXEC:-}" ]] && return 0
    command -v flock > /dev/null || return 0
    exec 9> "$STATE_DIR/lock"
    flock -n 9 || die "another deploy is running (lock: $STATE_DIR/lock)"
}

# If the commit being deployed has a different deploy.sh, run that version instead (from a temp copy, before anything
# changes), so a fix to this script applies to the deploy that brings it. ZENITH_DEPLOY_REEXEC stops it looping.
maybe_reexec() {
    [[ -n "${ZENITH_DEPLOY_REEXEC:-}" ]] && return 0
    local self="${BASH_SOURCE[0]}" new_blob tmp
    [[ -f "$self" ]] || return 0
    new_blob="$(git rev-parse -q --verify "$TARGET:deploy/deploy.sh")" || return 0
    [[ "$(git hash-object "$self")" == "$new_blob" ]] && return 0
    tmp="$(mktemp "${TMPDIR:-/tmp}/zenith-deploy.XXXXXX")"
    git cat-file blob "$new_blob" > "$tmp"
    step "deploy.sh changed in $(short "$TARGET"); continuing with the new version"
    exec env ZENITH_DEPLOY_REEXEC=1 ZENITH_DEPLOY_TMP="$tmp" ZENITH_APP_DIR="$APP_DIR" bash "$tmp" "${ORIG_ARGS[@]}"
}

# The old deploy script left the checkout on a detached commit. Point the branch at that commit (no files change) so
# the fast-forward below moves the branch, and plain `git pull` works again.
ensure_on_branch() {
    local branch
    branch="$(git symbolic-ref -q --short HEAD || true)"
    [[ "$branch" == "$BRANCH" ]] && return 0
    [[ -z "$branch" ]] || die "the checkout is on branch '$branch'; switch back with: git checkout $BRANCH"
    if git show-ref -q --verify "refs/heads/$BRANCH" && ! git merge-base --is-ancestor "$BRANCH" HEAD; then
        die "the checkout is detached and local '$BRANCH' isn't behind it; fix by hand (git status, git log)"
    fi
    info "The checkout is detached at $(short HEAD); moving branch $BRANCH there (no files change)."
    run git checkout --quiet -B "$BRANCH" HEAD
    run git branch --quiet --set-upstream-to="origin/$BRANCH" "$BRANCH"
}

# ---------------------------------------------------------------------------------------------------- one-time setup
# find_site NAME: the real file (symlinks resolved) in sites-enabled whose server_name lists exactly NAME
find_site() {
    local name="${1//./\\.}" f
    for f in "$NGINX_SITES_DIR"/*; do
        [[ -f "$f" ]] || continue
        if grep -qE "^[[:space:]]*server_name([[:space:]]+[^;]*)?[[:space:]]${name}([[:space:];]|$)" "$f" 2> /dev/null; then
            readlink -f "$f"
            return 0
        fi
    done
    return 1
}

setup_nginx() {
    step "nginx: API upload limit $NGINX_BODY_LIMIT (CSV imports send up to 2 MB)"
    command -v nginx > /dev/null || [[ -x /usr/sbin/nginx ]] || die "nginx isn't installed here"
    local api_host="${PUBLIC_API_URL#*://}" site_host="${PUBLIC_SITE_URL#*://}"
    api_host="${api_host%%/*}"
    site_host="${site_host%%/*}"
    local api_file web_file
    api_file="$(find_site "$api_host")" || die "no site in $NGINX_SITES_DIR has server_name $api_host"
    web_file="$(find_site "$site_host")" || die "no site in $NGINX_SITES_DIR has server_name $site_host"
    info "API site:     $api_file"
    info "Website site: $web_file"

    # The website is served straight from the build folder; only check it, never edit it
    if grep -qE "^[[:space:]]*root[[:space:]]+$FRONTEND/dist/?;" "$web_file"; then
        ok "website root is $FRONTEND/dist"
    else
        warn "the website's root in $web_file is not $FRONTEND/dist:" \
            "$(grep -E '^[[:space:]]*root[[:space:]]' "$web_file" | head -n 1 | xargs)"
        warn "this script builds into $FRONTEND/dist; point root there (docs/nginx-hardening.md)"
    fi

    local edited
    edited="$(mktemp)"
    if grep -qE '^[[:space:]]*client_max_body_size[[:space:]]' "$api_file"; then
        sed -E "s/^([[:space:]]*client_max_body_size[[:space:]]+)[^;]+;.*/\1${NGINX_BODY_LIMIT};  # CSV imports send up to 2 MB/" \
            "$api_file" > "$edited"
    else
        # not set at all (nginx's default is 1m): add it after each server_name line for the API
        awk -v host="$api_host" -v limit="$NGINX_BODY_LIMIT" '
            { print }
            $1 == "server_name" {
                for (i = 2; i <= NF; i++) { n = $i; sub(/;$/, "", n); if (n == host) hit = 1 }
                if (hit) { match($0, /^[[:space:]]*/); printf "%sclient_max_body_size %s;  # CSV imports send up to 2 MB\n", substr($0, 1, RLENGTH), limit }
                hit = 0
            }' "$api_file" > "$edited"
    fi

    grep -qE '^[[:space:]]*client_max_body_size' "$edited" ||
        die "couldn't find a server_name $api_host line in $api_file to add client_max_body_size to"
    # Compare only the directive values, so an identical setting with a different comment is still "no change"
    if diff -q <(grep -E '^[[:space:]]*client_max_body_size' "$api_file" | sed 's/#.*//;s/[[:space:]]//g') \
        <(grep -E '^[[:space:]]*client_max_body_size' "$edited" | sed 's/#.*//;s/[[:space:]]//g') > /dev/null; then
        ok "already client_max_body_size $NGINX_BODY_LIMIT; nothing to change"
        rm -f "$edited"
        return 0
    fi
    diff -u "$api_file" "$edited" | sed 's/^/      /' || true
    if ((DRY_RUN)); then
        dry "back up both site files to ~/nginx-backup-<time>/, write the change above, sudo nginx -t, reload nginx"
        rm -f "$edited"
        return 0
    fi

    local backup="$HOME/nginx-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup"
    cp "$api_file" "$backup/" && cp "$web_file" "$backup/"
    info "Backed up the site files to $backup"
    # cp onto the existing file keeps its owner and mode
    sudo cp "$edited" "$api_file"
    rm -f "$edited"
    if sudo nginx -t 2> "$backup/nginx-t.log"; then
        sudo systemctl reload nginx
        ok "nginx reloaded with client_max_body_size $NGINX_BODY_LIMIT"
    else
        sed 's/^/      /' "$backup/nginx-t.log" >&2
        sudo cp "$backup/$(basename "$api_file")" "$api_file"
        sudo nginx -t > /dev/null 2>&1 && info "restored $api_file from $backup; nginx was not reloaded"
        die "nginx rejected the new config; restored the old file"
    fi
    # A 1 MB POST must now reach the API (405 from /health) instead of nginx's 413
    local code
    code="$(head -c 1048576 /dev/zero | curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
        -H 'Content-Type: application/octet-stream' --data-binary @- "$PUBLIC_API_URL/health" 2> /dev/null || true)"
    if [[ "$code" == 413 ]]; then
        warn "a 1 MB upload still gets 413: another client_max_body_size (nginx.conf http block?) is lower"
    else
        ok "a 1 MB upload reaches the API ($code)"
    fi
}

install_backups() {
    step "Installing the nightly database backup (zenith-backup.timer)"
    local unit tmp user
    user="$(id -un)"
    for unit in zenith-backup.service zenith-backup.timer; do
        tmp="$(mktemp)"
        sed -e "s#/home/deploy/walletapp#$APP_DIR#g" -e "s#^User=.*#User=$user#" "$APP_DIR/deploy/$unit" > "$tmp"
        if [[ -f "/etc/systemd/system/$unit" ]] && cmp -s "$tmp" "/etc/systemd/system/$unit"; then
            ok "$unit is already up to date"
        else
            run sudo install -m 0644 "$tmp" "/etc/systemd/system/$unit"
        fi
        rm -f "$tmp"
    done
    run sudo systemctl daemon-reload
    run sudo systemctl enable --now zenith-backup.timer
    # one run now, under systemd, so a problem shows up today rather than at 03:30
    run sudo systemctl start zenith-backup.service
    ((DRY_RUN)) || ok "timer installed; next run: $(systemctl show -p NextElapseUSecRealtime --value zenith-backup.timer 2> /dev/null || echo '?')." \
        "Backups go to $(backup_dir)"
}

# ---------------------------------------------------------------------------------------------------- deploy steps
backup_db() {
    local db dir
    if ! db="$(db_path)"; then
        warn "DATABASE_URL isn't SQLite; back it up yourself"
        return 0
    fi
    if [[ ! -f "$db" ]]; then
        warn "no database at $db yet; nothing to back up"
        return 0
    fi
    dir="$(backup_dir)"
    if ((DRY_RUN)); then
        dry "back up $db to $dir/walletdatabase-<time>-pre-deploy.db.gz (+ integrity check, keep the last 30)"
        return 0
    fi
    BACKUP_DIR="$dir" APP_DIR="$APP_DIR" bash "$APP_DIR/deploy/zenith-backup.sh" pre-deploy | sed 's/^/    /'
    BACKUP_FILE="$(ls -1t "$dir"/walletdatabase-*-pre-deploy.db.gz | head -n 1)"
    SCHEMA_BEFORE="$(schema_fingerprint)"
}

build_website() {
    rm -rf "$FRONTEND/dist-next"
    # Same build as `npm run build`, into dist-next so the live dist stays complete until the swap. --outDir doesn't
    # change what's built (public/ files like robots.txt and sitemap.xml are copied in too); --emptyOutDir is only
    # needed because Vite asks before emptying a folder other than dist.
    (cd "$FRONTEND" && npm ci --no-audit --no-fund && npm run build -- --outDir dist-next --emptyOutDir)
    [[ -s "$FRONTEND/dist-next/index.html" ]] || die "the build has no index.html"
}

# Puts the new build live: two renames, so the site is never half-copied or empty. The previous build stays in
# dist-prev for a rollback.
swap_website() {
    local f
    # Keep the previous build's hashed files for a week: a tab opened before the deploy still lazy-loads its old
    # page chunks (pages are React.lazy), which would 404 if they vanished with the old dist.
    if [[ -d "$FRONTEND/dist/assets" && -d "$FRONTEND/dist-next/assets" ]]; then
        for f in "$FRONTEND"/dist/assets/*; do
            [[ -e "$f" && ! -e "$FRONTEND/dist-next/assets/${f##*/}" ]] && cp -pR "$f" "$FRONTEND/dist-next/assets/"
        done
        find "$FRONTEND/dist-next/assets" -type f -mtime +7 -delete
    fi
    rm -rf "$FRONTEND/dist-prev"
    if [[ -d "$FRONTEND/dist" ]]; then
        mv "$FRONTEND/dist" "$FRONTEND/dist-prev"
        WEBSITE_SWAPPED=1
    else
        WEBSITE_SWAPPED=2  # there was no previous build
    fi
    mv "$FRONTEND/dist-next" "$FRONTEND/dist"
}

# Public checks run after the deploy is already live and only warn: the local check has proven the new API runs, so a
# failure here is nginx, TLS or DNS, which rolling back the code wouldn't fix (and would bounce a working API).
public_checks() {
    local tries code body want
    for tries in 1 2 3; do
        api_ok "$PUBLIC_API_URL" 10 && break
        ((tries < 3)) && sleep 2
    done
    if api_ok "$PUBLIC_API_URL" 10; then
        ok "public API $PUBLIC_API_URL"
    else
        warn "public API $PUBLIC_API_URL isn't answering (nginx? sudo systemctl status nginx)"
        WARNINGS=$((WARNINGS + 1))
    fi
    want="$(entry_script "$FRONTEND/dist/index.html")"
    body="$(curl -fsS --max-time 10 "$PUBLIC_SITE_URL/" 2> /dev/null || true)"
    code="$(http_code "$PUBLIC_SITE_URL/" 10)"
    if [[ "$code" != 200 ]]; then
        warn "website $PUBLIC_SITE_URL answered $code"
        WARNINGS=$((WARNINGS + 1))
    elif [[ -n "$want" && "$body" != *"$want"* ]]; then
        warn "website $PUBLIC_SITE_URL doesn't serve the new build; is nginx's root $FRONTEND/dist?"
        WARNINGS=$((WARNINGS + 1))
    else
        ok "website $PUBLIC_SITE_URL serves the new build"
    fi
}

print_restore_help() {
    local db
    db="$(db_path 2> /dev/null || echo "$APP_DIR/walletdatabase.db")"
    info "To restore the pre-deploy database by hand (loses every write since $(basename "${BACKUP_FILE:-the backup}")):"
    info "  sudo systemctl stop $SERVICE"
    info "  gunzip -c '${BACKUP_FILE:-<backup>.db.gz}' > '$db.restore'"
    info "  rm -f '$db-wal' '$db-shm' && mv '$db.restore' '$db'"
    info "  sudo systemctl start $SERVICE"
}

restore_db() {
    local db
    db="$(db_path)"
    sudo systemctl stop "$SERVICE" &&
        gunzip -c "$BACKUP_FILE" > "$db.restore" &&
        rm -f "$db-wal" "$db-shm" &&
        mv "$db.restore" "$db" &&
        sudo systemctl start "$SERVICE"
}

# Rollback after a failure from the fast-forward on. Errors are reported, not fatal: get as far back as possible.
rollback() {
    set +e
    trap - ERR
    trap '' INT TERM  # a second Ctrl-C mustn't stop a rollback halfway
    PHASE="rollback"
    printf '\n%s==> Deploy failed; rolling back to %s%s\n' "$RED$BOLD" "$(short "$ROLLBACK_TO")" "$RESET" >&2
    [[ -n "${FAIL_REASON:-}" ]] || err "step failed at line ${ERR_LINE:-?}: ${ERR_CMD:-?}"
    ((BACKEND_RESTARTED)) && show_journal
    local problems=0

    cd "$APP_DIR" || return
    if [[ "$(git rev-parse HEAD)" != "$ROLLBACK_TO" ]]; then
        # --keep (not --hard): with --force there may be local edits, which this keeps instead of wiping
        if git reset --quiet --keep "$ROLLBACK_TO"; then
            ok "code back at $(git log -1 --format='%h %s')"
        else
            err "git reset to $(short "$ROLLBACK_TO") failed; run: git reset --keep $ROLLBACK_TO"
            problems=1
        fi
    fi
    if ((PACKAGES_CHANGED)); then
        if uv sync --frozen --no-dev --quiet; then ok "Python packages back"; else err "uv sync failed"; problems=1; fi
    fi

    rm -rf "$FRONTEND/dist-next"
    if ((WEBSITE_SWAPPED == 1)) && [[ -d "$FRONTEND/dist-prev" ]]; then
        rm -rf "$FRONTEND/dist-failed"
        mv "$FRONTEND/dist" "$FRONTEND/dist-failed" && mv "$FRONTEND/dist-prev" "$FRONTEND/dist" &&
            rm -rf "$FRONTEND/dist-failed" && ok "previous website back in frontend/dist"
    else
        ok "website untouched (the new build never went live)"
    fi

    if ((BACKEND_RESTARTED)); then
        sudo systemctl restart "$SERVICE"
        if wait_healthy; then
            ok "API healthy again on $(short "$ROLLBACK_TO")"
        else
            err "the API isn't healthy after the rollback either: journalctl -u $SERVICE -n 100"
            problems=1
        fi
    elif api_ok "$LOCAL_API_URL"; then
        ok "API was never restarted and is still healthy"
    fi

    # The database. Not restored by default, on purpose:
    #  - If the new API never started, nothing touched the database.
    #  - If it started, its startup may have run migrations: create_all (new tables) and ADDED_COLUMNS (new columns).
    #    Both are additive, and the old code simply ignores extra tables and columns, so it runs fine on the migrated
    #    database. Restoring the backup would instead throw away every write users made since it (sign-ups, trades).
    # So only with --restore-db-on-rollback, and only when the new API started AND the schema actually changed, is the
    # backup put back; otherwise the manual steps are printed for the rare migration that isn't additive.
    if ((BACKEND_RESTARTED)) && [[ -n "${BACKUP_FILE:-}" ]]; then
        local schema_after
        schema_after="$(schema_fingerprint)"
        if [[ "$schema_after" != "$SCHEMA_BEFORE" || "$schema_after" == unknown ]]; then
            if ((RESTORE_DB_ON_ROLLBACK)); then
                info "The new API changed the database schema; restoring $BACKUP_FILE (--restore-db-on-rollback)"
                if restore_db && wait_healthy; then ok "database restored"; else err "database restore failed"; problems=1; fi
            else
                warn "the new API changed the database schema (added tables/columns). The database was kept:" \
                    "the old code ignores additive changes, and restoring would lose writes made since the backup."
                print_restore_help
            fi
        else
            ok "database kept (the schema didn't change, so the old code runs on it as before)"
        fi
    else
        ok "database untouched (the new API never ran)"
    fi

    printf '\n'
    if ((problems)); then
        err "Rollback incomplete; see above. Backup: ${BACKUP_FILE:-none}"
    else
        printf '%sRolled back to %s in %ss.%s The deploy of %s did not go live.\n' "$YELLOW$BOLD" "$(short "$ROLLBACK_TO")" \
            "$((SECONDS - START))" "$RESET" "$(short "$TARGET")" >&2
    fi
    record_history "rolled-back"
}

record_history() {
    ((DRY_RUN)) && return 0
    mkdir -p "$STATE_DIR"
    printf '%s  %s -> %s  %s\n' "$(date '+%Y-%m-%d %H:%M')" "$(short "$ROLLBACK_TO")" "$(short "$TARGET")" "$1" \
        >> "$STATE_DIR/history"
}

on_exit() {
    local status=$?
    [[ -n "${SUDO_KEEPALIVE_PID:-}" ]] && kill "$SUDO_KEEPALIVE_PID" 2> /dev/null
    [[ -n "${ZENITH_DEPLOY_TMP:-}" ]] && rm -f "$ZENITH_DEPLOY_TMP"
    if ((status != 0)); then
        if [[ "$PHASE" == deploy ]]; then
            rollback
        elif [[ "$PHASE" == check ]]; then
            [[ -n "${FAIL_REASON:-}" ]] || err "failed at line ${ERR_LINE:-?}: ${ERR_CMD:-?}"
            err "Stopped before changing the deployed code; the site and API are as they were."
        fi
    fi
    exit "$status"
}

# ---------------------------------------------------------------------------------------------------- main
main() {
    local arg
    for arg in "$@"; do
        case "$arg" in
            --force | -f) FORCE=1 ;;
            --dry-run | -n) DRY_RUN=1 ;;
            --status) STATUS=1 ;;
            --setup-nginx) SETUP_NGINX=1 ;;
            --install-backups) INSTALL_BACKUPS=1 ;;
            --restore-db-on-rollback) RESTORE_DB_ON_ROLLBACK=1 ;;
            -h | --help) usage; exit 0 ;;
            *) usage >&2; printf '\nUnknown option: %s\n' "$arg" >&2; exit 2 ;;
        esac
    done

    cd "$APP_DIR"
    if ((STATUS)); then
        show_status
        exit 0
    fi

    START=$SECONDS PHASE="check" WARNINGS=0
    BACKEND_RESTARTED=0 WEBSITE_SWAPPED=0 PACKAGES_CHANGED=0 BACKUP_FILE="" SCHEMA_BEFORE="unknown"
    TARGET="" ROLLBACK_TO="$(git rev-parse HEAD)"
    trap on_exit EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'ERR_LINE=$LINENO ERR_CMD=$BASH_COMMAND' ERR
    ((DRY_RUN)) && printf '%sDry run: nothing is changed (git fetch still runs).%s\n' "$BOLD" "$RESET"

    preflight
    acquire_lock

    step "Fetching origin/$BRANCH"
    git fetch --quiet origin "$BRANCH"
    TARGET="$(git rev-parse "origin/$BRANCH")"
    maybe_reexec
    start_sudo_keepalive
    ensure_on_branch
    git merge-base --is-ancestor HEAD "$TARGET" ||
        die "HEAD $(short HEAD) has commits that aren't on origin/$BRANCH, so it can't fast-forward; check git log"

    ((SETUP_NGINX)) && setup_nginx
    ((INSTALL_BACKUPS)) && install_backups

    # What's running is the last commit this script deployed. Without that record (first run, or after a manual
    # `git pull`, which updates the files but not the running API or the built site) the current checkout is deployed.
    local head deployed=""
    head="$(git rev-parse HEAD)"
    if [[ -f "$STATE_DIR/deployed" ]]; then
        deployed="$(cat "$STATE_DIR/deployed")"
        git cat-file -e "$deployed^{commit}" 2> /dev/null || deployed=""
    fi
    if [[ "$head" == "$TARGET" && "$deployed" == "$TARGET" ]] && ((!FORCE)); then
        ok "Already deployed: $(git log -1 --format='%h %s (%cr)'). Nothing to do; --force redeploys anyway."
        PHASE="done"
        exit 0
    fi
    ROLLBACK_TO="${deployed:-$head}"
    step "Deploying $(short "$ROLLBACK_TO") -> $(short "$TARGET")"
    if [[ "$ROLLBACK_TO" != "$TARGET" ]]; then
        git log --oneline --no-decorate -n 20 "$ROLLBACK_TO..$TARGET" | sed 's/^/      /'
    else
        info "redeploying the same commit"
    fi
    [[ -z "$deployed" ]] && info "No record of a previous deploy by this script: a rollback can bring back the website" \
        "and restart the API, but can't go further back than $(short "$head")."

    step "Backing up the database"
    backup_db

    ((DRY_RUN)) || PHASE="deploy"  # from here on, any failure rolls back

    step "Updating the code"
    if [[ "$head" != "$TARGET" ]]; then
        run git merge --ff-only --quiet "$TARGET"
        ok "checkout at $(short "$TARGET")"
    else
        ok "checkout already at $(short "$TARGET")"
    fi

    step "Python packages"
    PACKAGES_CHANGED=1
    if [[ -f "$APP_DIR/uv.lock" ]]; then
        run uv sync --frozen --no-dev
    else
        warn "no uv.lock; resolving fresh"
        run uv sync --no-dev
    fi

    step "Building the website into frontend/dist-next"
    if ((DRY_RUN)); then
        dry "cd frontend && npm ci && npm run build -- --outDir dist-next --emptyOutDir"
    else
        build_website
        ok "built ($(du -sh "$FRONTEND/dist-next" | cut -f1)); the live site still serves the old build"
    fi

    step "Restarting the API ($SERVICE)"
    BACKEND_RESTARTED=1
    run sudo systemctl restart "$SERVICE"
    if ((DRY_RUN)); then
        dry "wait up to ${HEALTH_TIMEOUT}s for $LOCAL_API_URL/health (or /auth/providers on old commits)"
    else
        wait_healthy || die "the API didn't become healthy within ${HEALTH_TIMEOUT}s"
        ok "API healthy at $LOCAL_API_URL"
    fi

    step "Switching the website to the new build"
    if ((DRY_RUN)); then
        dry "frontend/dist -> frontend/dist-prev, frontend/dist-next -> frontend/dist"
    else
        swap_website
        ok "frontend/dist is live (previous build in frontend/dist-prev)"
    fi

    ((DRY_RUN)) || printf '%s\n' "$TARGET" > "$STATE_DIR/deployed"
    PHASE="done"
    record_history "ok"

    step "Public checks"
    if ((DRY_RUN)); then
        dry "check $PUBLIC_API_URL/health and that $PUBLIC_SITE_URL serves the new build"
        printf '\n%sDry run: would deploy %s->%s.%s\n' "$GREEN$BOLD" "$(short "$ROLLBACK_TO")" "$(short "$TARGET")" "$RESET"
        exit 0
    fi
    public_checks

    printf '\n%sDeployed %s→%s in %ss.%s' "$GREEN$BOLD" "$(short "$ROLLBACK_TO")" "$(short "$TARGET")" \
        "$((SECONDS - START))" "$RESET"
    ((WARNINGS)) && printf ' %s(%s warning(s) above)%s' "$YELLOW" "$WARNINGS" "$RESET"
    printf '\n'
    [[ -n "$BACKUP_FILE" ]] && info "Database backup: $BACKUP_FILE"
    return 0
}

main "$@"
