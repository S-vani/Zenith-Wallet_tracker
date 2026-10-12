# WalletTracker

## Running locally

You need Python 3.11+ and Node.js. Backend settings come from `.env` in the project root, and the frontend reads `VITE_BACKEND_URL` from `frontend/.env`.

```bash
# 1. Python packages (one time)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip install -r requirements.txt

# 2. Start the backend (port 8000) and frontend (port 5173) together
npm run dev
```

`npm run dev:backend` and `npm run dev:frontend` start just one of them. You can also run the backend on its own with `python backend/main.py`.

> **Windows:** if PowerShell says *"npm.ps1 cannot be loaded because running scripts is disabled"*, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `npm.cmd run dev` instead.

## Running tests

```bash
# one time: test packages
uv sync                                               # or: .venv\Scripts\pip install -r requirements-dev.txt
npm --prefix frontend install

# run everything (backend + frontend)
npm test                                              # Windows PowerShell without script permission: npm.cmd test
```

- `npm run test:backend` runs the pytest suite in `tests/` with the `.venv` Python. Extra pytest arguments go after `--`, e.g. `npm run test:backend -- -k dashboard`.
- `npm run test:frontend` runs the Vitest suite in `frontend/test/` (`npm --prefix frontend run test:watch` re-runs on save).
- The backend tests use a throwaway SQLite database, a test JWT secret and no email account, and block all network access (exchange rates, Yahoo Finance, TwelveData and CoinGecko are faked), so they never touch `walletdatabase.db`, your `.env` values or any real API.
- Tests marked `xfail` document known bugs; once a bug is fixed its test reports `XPASS(strict)` and fails, so remove the `xfail` marker then.
