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
