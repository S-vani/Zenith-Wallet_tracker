# Zenith Wallet Tracker

Stock & crypto portfolio tracker. Users log buys/sells; the app shows holdings, portfolio value/returns over time,
price charts, a symbol search with a built-in rules-based market analyst, and account settings (currency CAD/USD/EUR).
Live at https://zenithwalletracker.ca (frontend) with the API at https://api.zenithwalletracker.ca.

## Layout
- `backend/` — FastAPI (Python 3.11+), async SQLAlchemy, fastapi-users JWT auth. Imports use the `backend.` prefix,
  so run from the project root (`backend/main.py` also fixes `sys.path` when run directly).
  - `main.py` — app, CORS (`FRONTEND_URL`, comma-separated), JSON 500 handler, 422 handler that never echoes inputs.
  - `routes/assets.py` — transactions CRUD + filters, holdings, dashboard, price/portfolio history, stock/crypto
    search, user info/email, `DELETE /user` (account deletion: transactions + OAuth links + user, required by the
    app stores). `routes/oauth.py` — Google sign-in. `routes/analyst.py` — `GET /analyst`.
  - `services/asset_services.py` — pricing (yfinance), FX conversion (open.er-api, 60 s cache), holdings math,
    `rebuild_symbol_ledger` (replays a symbol's buys/sells; used by PUT/DELETE to keep history valid).
  - `analyst/` — market analyst: `data.py` (collects data), `indicators.py` (pure maths), `engine.py` (rules →
    report), `gemini.py` (optional rewording), `service.py` (DB cache, rate limits), `schema.py` (response model).
  - `db_models/assets.py` — `User`, `Transaction`, `OAuthAccount`, `UserManager` (password rules, verification email).
- `frontend/` — React 19 + Vite + recharts. `src/services/api.js` is the only place that calls the backend
  (`request()` adds the token, maps errors to readable messages, logs out on 401/403).
  - `pages/` (one per route), `Dashboard/`, `Holdings/`, `Transactions/`, `Search/`, `Analyst/`, `Authentication/`.
    `pages/PrivacyPage.jsx` (`/privacy`, public) is the privacy policy + "not financial advice" disclaimer the app
    stores require — update it whenever the app starts collecting or sending data somewhere new.
  - `context/UserContext.jsx` (current user + currency), `utils/format.js` (money/price/percent formatting — use
    `formatPrice` for asset prices so tiny coins never show $0.00), `utils/chart.js`, `utils/toast.js` (`showToast`).
  - CSS in `src/css/` with design tokens in `Global.css` (navy theme). Phones get a bottom tab bar (≤768px).
- iOS app — Capacitor 8 wraps the same frontend (`frontend/capacitor.config.json`, Xcode project in `frontend/ios/`,
  Swift Package Manager, app id `ca.zenithwalletracker.app`). App-only code lives in `src/native/` and every part of
  it checks `isNative` first, so the website is unaffected (`test/native.test.js` guards this): Keychain copy of the
  token (cleared on a fresh install), Face ID lock (decisions in `lockRules.js`: only a quick return to an app that
  was *unlocked* skips Face ID), haptics, share sheet, pull to refresh (`useRefreshKey`), offline cache of the
  portfolio screens (`offlineCache.js`, used by `api.js`), offline banner, labelled tab bar without log out
  (`html.native` CSS in `Native.css`), splash/status bar, no pinch zoom. In the app `/` skips the marketing page and
  Google sign-in is hidden (web views can't use it; would also need Sign in with Apple). Backend CORS always allows
  `capacitor://localhost`.
  - Build the app with `npm run build:ios` (Vite into `dist-ios/`, drops website-only files like the demo video,
    then `cap sync ios`); the website's `dist/` is separate. Cloud builds: `codemagic.yaml` (no Mac needed).
  - `ios/App/App/PrivacyInfo.xcprivacy` is Apple's privacy manifest (UserDefaults reason CA92.1, collected data);
    keep it, the App Privacy answers and `/privacy` in step. Icons/splash come from `frontend/assets/`
    (`npx @capacitor/assets@3.0.5 generate --ios ...`, not installed: it pulls vulnerable deps).
- Fonts: Lato is bundled (`@fontsource/lato`, imported in `main.jsx`); no Google Fonts requests.
- `tests/` — pytest (offline: network blocked, prices/FX/yfinance/HTTP stubbed, temp SQLite DB).
  `frontend/test/` — Vitest for pure utils.
- `scripts/dev.mjs`, `scripts/test-backend.mjs` — used by the root `package.json`.

## Commands (project root)
- `npm run dev` — backend :8000 + frontend :5173 (uses `.venv`). `dev:backend` / `dev:frontend` for one.
- `npm test` — all tests (pytest then Vitest). `npm run test:backend -- -k name` to filter.
- Frontend: `npx eslint .` and `npx vite build` in `frontend/`.
- Windows PowerShell blocks `npm.ps1` unless the execution policy allows it — use `npm.cmd` or Git Bash.
- Python deps: `uv sync` (or `pip install -r requirements-dev.txt`). After changing deps run
  `uv export --format requirements-txt --no-hashes --no-dev --no-emit-project -o requirements.txt`.

## Data & money conventions
- Transactions store prices in **CAD**; API responses convert to the user's currency (`get_conversion_factor`).
  Prices typed by the user are converted to CAD on create/update.
- Quantities/prices are `Numeric(20, 10)`; compare quantities as `Decimal` (see `current_quantity`).
- Timestamps are stored as naive UTC; filters convert offset-aware input to UTC first.
- Crypto `api_id` is the lowercase CoinGecko symbol (e.g. `btc`); search results also carry `coin_id` (`bitcoin`).
- Stock prices come in the listing currency (Yahoo `info.currency`, e.g. USD, CAD, EUR, `GBp` = pence) and are
  converted to CAD with `get_native_to_cad_factor` (USD cross rates, cached 1 h), then to the user's currency.
  Rows with a missing (NaN) close are skipped.
- Stock search uses TwelveData only for `symbol_search` (1 credit; free plan = 8 credits/min) with matches cached
  10 min per query; prices come from Yahoo (`get_latest_stock_quotes`). Don't reintroduce TwelveData `/quote`
  (1 credit per symbol): it used up the limit and errors showed as "no results". Provider errors → 503 with a message.
- `/prices/history` falls back to CoinGecko for coins Yahoo doesn't list as `SYMBOL-USD` (e.g. PEPE).

## Market analyst (`GET /analyst?symbol=&type=stock|crypto[&coin_id=][&refresh=true]`)
- Free: no paid AI. A rules engine scores trend (50/200-day averages), momentum (30/90-day returns), RSI, volume
  trend, and stock fundamentals/valuation/analyst targets (Yahoo) or crypto liquidity/ATH/BTC correlation
  (CoinGecko). Sentiment = weighted score (> 0.15 bullish, < -0.15 bearish). Every sentence is built from numbers
  that also appear in `metrics`.
- Scenario price ranges are log-normal, zero drift, from 90-day realized volatility (base = middle 50%,
  bull/bear = 75–95th / 5–25th percentiles); omitted with < 60 data points. Not predictions — the UI says so.
- Optional `GEMINI_API_KEY` (free tier) rewords the text only; `validate_rewrite` rejects any new numbers, changed
  list sizes, contradictions → falls back to rules wording. `engine` field tells the UI which wrote it.
- Stablecoins (CoinGecko "Stablecoins" category) are always neutral with a peg/exchange-rate story; ETFs skip
  company fundamentals; histories under 120 days cap confidence at low and relabel windows honestly.
- Wording rules: no buy/sell advice (analyst consensus is shown as words + 1–5 score), conditions and price-level
  advice are written from where the price actually is, numbers use a real minus sign.
- Cached in table `analyst_reports` (1 h stocks / 30 min crypto, per asset + currency). Manual refresh after 5 min;
  30 fresh reports per user per hour. No news feed is connected (stated in `limitations`).

## Environment (`.env` in project root; never commit it)
`SECRET`, `DATABASE_URL` (default `sqlite+aiosqlite:///./walletdatabase.db`, anchored to project root),
`FRONTEND_URL`, `BACKEND_URL` (public API URL, used for the Google callback), `API_KEY` (TwelveData),
`API_KEY_COINEGECKO` (CoinGecko demo), `GMAIL_USER`/`GMAIL_PASS` (verification email; if empty the link is logged),
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (Google sign-in; button hidden without them), `GEMINI_API_KEY`
(+ optional `GEMINI_MODEL`, default `gemini-2.5-flash`). Frontend: `frontend/.env` → `VITE_BACKEND_URL`.

## Deploying (server: `~/walletapp` as user `deploy`)
`git pull` → `uv sync` (or `.venv/bin/pip install -r requirements.txt`) → `cd frontend && npm ci && npm run build`
(copy `dist` if nginx serves `/var/www/html`) → **restart the backend service** (a pull alone doesn't reload Python;
this was missed before, leaving the old API running). Check: `curl https://api.zenithwalletracker.ca/auth/providers`.

## Working notes
- Keep changes in the existing style (JSX with 4-space indent, plain CSS files per area, small comments explaining
  "why"). Don't commit `.idea/` or `__pycache__/`.
- For local manual testing without touching the real DB, run the backend with `DATABASE_URL` pointing at a scratch
  copy and `GMAIL_USER=`/`GMAIL_PASS=` so no email is sent. Don't commit `.claude/launch.json` (machine-specific).
- Never log in to production with real credentials from automation; test on localhost with test accounts.
