# Running Zenith in production

The server runs everything as the `deploy` user from `/home/deploy/walletapp`. The files in `deploy/` are meant to be
copied into place once; after that, every release is `bash deploy/deploy.sh`.

## One-time setup

1. **API service.** Copy `deploy/walletapp-backend.service` to `/etc/systemd/system/`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now walletapp-backend`. It runs one uvicorn worker on
   `127.0.0.1:8000` (the in-memory rate limits need exactly one process). Make sure port 8000 isn't reachable from
   outside (`sudo ufw deny 8000` or equivalent); only nginx should talk to it.
2. **Backups.** `sudo apt install sqlite3 rclone`, then copy `deploy/zenith-backup.service` and `.timer` to
   `/etc/systemd/system/` and `sudo systemctl enable --now zenith-backup.timer`. Copies go to
   `/home/deploy/backups/zenith` and are kept 30 days. For off-site copies, set up an encrypted rclone remote
   (`rclone config`, a Backblaze B2 or S3 remote wrapped in a "crypt" remote) and add `BACKUP_REMOTE=name:bucket` to
   `.env`. Run `bash deploy/zenith-backup.sh` once by hand to check it works.
3. **Test a restore once** (on a copy, never over the live file):
   `gunzip -k walletdatabase-….db.gz && sqlite3 walletdatabase-….db 'select count(*) from user;'`.
   To restore for real: `sudo systemctl stop walletapp-backend`, copy the unzipped file over `walletdatabase.db`,
   delete `walletdatabase.db-wal` and `-shm`, start the service.
4. **Logs: 14 days.** Copy `deploy/journald-zenith.conf` to `/etc/systemd/journald.conf.d/zenith.conf` and restart
   `systemd-journald`; set up the nginx log format and logrotate from `docs/nginx-hardening.md` section 4.
5. **Uptime monitor.** Point a free monitor (UptimeRobot, Better Stack) at `https://api.zenithwalletracker.ca/health`
   every 5 minutes with email alerts. It checks the database too, so a dead disk or locked file shows up.
6. **`.env`** (see CLAUDE.md for the full list). New for the App Store launch:
   - `SECRET` must be at least 32 characters (the API refuses to start otherwise). Generate one with
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs everyone out.
   - `MIN_IOS_APP_VERSION`: leave empty until you need it. When an API change would break older app versions, set it
     to the first version that works (e.g. `1.2`); older apps then show "Update required" instead of breaking.
   - Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM` for a transactional email provider
     (Postmark, Amazon SES, Resend, Brevo) on your own domain, with SPF, DKIM and DMARC records for
     zenithwalletracker.ca. Without `SMTP_HOST` the old `GMAIL_USER`/`GMAIL_PASS` setup is used. Update the
     privacy policy's list of providers when you switch.
   - `GEMINI_API_KEY`: leave it **unset** unless the key has billing turned on. Google's terms only allow the paid
     tier for apps offered in the EU, UK or Switzerland; without it the analyst uses its own wording.

## Every release

```bash
cd ~/walletapp && git fetch && bash deploy/deploy.sh
```

It backs up the database, checks out `origin/main` (or the tag/commit you pass), installs the locked Python
packages, builds the website into `/var/www/html`, restarts the API and waits for `/health`. If the API doesn't come
back healthy it puts the previous commit back. Only deploy commits whose CI run is green.

The checkout ends up on a detached commit, which is expected; don't `git pull` in it any more, use the script.

## iOS app releases

Tag the commit `ios-v<version>` (e.g. `ios-v1.1`) and push the tag: Codemagic sets that as the app version, bumps
the build number and uploads to TestFlight. Deploy the API first if the app needs new API features, and keep API
changes additive (old app versions stay installed for months); use `MIN_IOS_APP_VERSION` when that's impossible.
