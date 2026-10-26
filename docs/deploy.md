# Deploying Zenith

The server runs everything as the `deploy` user from `/home/deploy/walletapp` (`~/walletapp`). nginx serves the
website straight from `~/walletapp/frontend/dist` and proxies `api.zenithwalletracker.ca` to the API on
`127.0.0.1:8000` (systemd service `walletapp-backend`). One script does the whole release.

## First time (once)

The script isn't on the server until the first pull, so this once by hand:

```bash
cd ~/walletapp && git pull --ff-only && bash deploy/deploy.sh --setup-nginx --install-backups
```

(If git says "You are not currently on a branch", the old script left the checkout detached: `git checkout main`
first.) This deploys the pulled commit, raises the API's upload limit to 3 MB for CSV imports (`--setup-nginx`) and
installs the nightly database backup (`--install-backups`). Both flags are safe to repeat; they change nothing the
second time. sudo asks for your password once.

## Every release

```bash
bash ~/walletapp/deploy/deploy.sh        # or: cd ~/walletapp && ./deploy.sh
```

Only deploy commits whose CI run is green. No `git pull` needed: the script fetches `origin/main` itself, and if
`deploy.sh` itself changed in the new commit it switches to the new version before doing anything.

What it does, stopping at the first problem:

1. **Checks** git, uv, npm, curl, a clean checkout, `SECRET` in `.env` (32+ characters, read the way the app reads
   it), 1 GB free disk and the service. A failure here changes nothing.
2. **Fetches** `origin/main`. Nothing new → it says so and exits.
3. **Backs up the database** to `~/walletapp-backups/walletdatabase-<time>-pre-deploy.db.gz` (a consistent SQLite
   copy, integrity-checked; `sqlite3` isn't required, Python's sqlite3 module is used without it). Keeps the last 30.
4. **Fast-forwards** to `origin/main`, `uv sync --frozen`, `npm ci`, builds the website into `frontend/dist-next`
   (the live `dist` is untouched while it builds).
5. **Restarts** `walletapp-backend` and waits up to 30 s for `http://127.0.0.1:8000/health`.
6. **Swaps the website**: `dist` → `dist-prev`, `dist-next` → `dist` (two renames, so the site is never blank),
   then checks `https://api.zenithwalletracker.ca/health` and that `https://zenithwalletracker.ca/` serves the new
   build. These public checks only warn: by then the new code is proven healthy locally.
7. Prints `Deployed <old>→<new> in Ns`.

## Flags

| Flag | |
|---|---|
| `--status` | deployed commit, what's new on `origin/main`, service and health, latest backup, recent deploys |
| `--dry-run` | prints every step without changing anything (only `git fetch` runs) |
| `--force` | redeploy even if nothing changed; also allows local changes in the checkout |
| `--setup-nginx` | one-time: backs up the two site files to `~/nginx-backup-<time>/`, sets `client_max_body_size 3m` in the API site, `nginx -t`, reload (puts the old file back if `nginx -t` fails) |
| `--install-backups` | one-time: installs `zenith-backup.timer` (nightly at 03:30 UTC) and runs one backup |
| `--restore-db-on-rollback` | let a rollback restore the pre-deploy database too (see below) |

## Rollback

Any failure after the fast-forward (a failed build, `uv sync`, or an API that doesn't come up healthy, or Ctrl-C) rolls
back by itself: the code goes back to the commit that was running, `uv sync`, the previous website returns from
`dist-prev` if it had been swapped, the API restarts and is health-checked, and the API's last log lines are shown.
`--status` lists recent deploys and rollbacks.

The **database is not restored** automatically. Startup migrations only add tables and columns, which the old code
ignores, while restoring would throw away every sign-up and trade made since the backup. If the failed API changed
the schema, the rollback says so and prints the restore commands, below. Pass `--restore-db-on-rollback` only for a
release whose migration the old code can't live with.

A failed deploy leaves `main` on the server behind `origin/main`, so the next run tries the same commit again: push a
fix first. To undo a release that deployed fine but turned out bad, `git revert` it on your machine, push, let CI
pass and deploy normally (the script always deploys `origin/main`).

## Restoring the database by hand

Backups: `~/walletapp-backups/` (`*-pre-deploy.db.gz` before each deploy, `*-nightly.db.gz` each night, 30 days).
Test a backup on a copy first: `gunzip -k <file>.db.gz` and open it with Python's sqlite3 or `sqlite3`.

```bash
sudo systemctl stop walletapp-backend
cd ~/walletapp
gunzip -c ~/walletapp-backups/walletdatabase-<time>-pre-deploy.db.gz > walletdatabase.db.restore
rm -f walletdatabase.db-wal walletdatabase.db-shm && mv walletdatabase.db.restore walletdatabase.db
sudo systemctl start walletapp-backend
```

Everything written after that backup is lost.

## One-time server setup (already done on the live server)

- **API service.** The installed unit may differ from `deploy/walletapp-backend.service`; the script never
  overwrites it, and `--status` says when they differ. To use the repo's version:
  `sudo cp deploy/walletapp-backend.service /etc/systemd/system/ && sudo systemctl daemon-reload &&
  sudo systemctl restart walletapp-backend`. It runs one uvicorn worker on `127.0.0.1:8000` (the in-memory rate limits
  need exactly one process) and has no `EnvironmentFile=`: the app reads `.env` itself, and systemd parses quotes
  differently. Keep port 8000 closed to the outside (`sudo ufw deny 8000`).
- **Off-site backups (optional).** `sudo apt install rclone`, set up an encrypted remote (`rclone config`: a B2 or S3
  remote wrapped in a "crypt" remote) and add `BACKUP_REMOTE=name:bucket` to `.env`.
- **Logs: 14 days.** Copy `deploy/journald-zenith.conf` to `/etc/systemd/journald.conf.d/zenith.conf` and restart
  `systemd-journald`; nginx log format and logrotate: `docs/nginx-hardening.md` section 4.
- **Uptime monitor.** Point a free monitor (UptimeRobot, Better Stack) at `https://api.zenithwalletracker.ca/health`
  every 5 minutes with email alerts. It checks the database too.
- **`.env`** (full list in CLAUDE.md):
  - `SECRET` at least 32 characters (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`); changing it
    signs everyone out.
  - `MIN_IOS_APP_VERSION`: empty until an API change would break older app versions; then the first version that
    works (e.g. `1.2`), and older apps show "Update required".
  - Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM` for a transactional provider on your own
    domain (SPF, DKIM, DMARC). Without `SMTP_HOST` the old `GMAIL_USER`/`GMAIL_PASS` setup is used. Update the
    privacy policy's list of providers when you switch.
  - `GEMINI_API_KEY`: leave it **unset** unless the key has billing on (Google's terms only allow the paid tier for
    apps offered in the EU, UK or Switzerland); without it the analyst uses its own wording.
  - `BACKUP_DIR` (default `~/walletapp-backups`), `BACKUP_REMOTE` (optional).

## iOS app releases

Tag the commit `ios-v<version>` (e.g. `ios-v1.1`) and push the tag: Codemagic sets that as the app version, bumps
the build number and uploads to TestFlight. Deploy the API first if the app needs new API features, and keep API
changes additive (old app versions stay installed for months); use `MIN_IOS_APP_VERSION` when that's impossible.
The iOS build (`dist-ios`) is separate from the website's `dist`, `dist-next` and `dist-prev`.
