# Zenith Wallet Tracker

Stock & crypto portfolio tracker. Users log buys/sells; the app shows holdings, portfolio value/returns over time,
price charts, a symbol search with a built-in rules-based market analyst, and account settings (currency CAD/USD/EUR).
Live at https://zenithwalletracker.ca (frontend) with the API at https://api.zenithwalletracker.ca.

## Layout
- `backend/` — FastAPI (Python 3.11+), async SQLAlchemy, fastapi-users JWT auth. Imports use the `backend.` prefix,
  so run from the project root (`backend/main.py` also fixes `sys.path` when run directly).
  - `main.py` — app, CORS (`FRONTEND_URL`, comma-separated), JSON 500 handler, 422 handler that never echoes inputs,
    security headers middleware; `/docs`/`/redoc`/`/openapi.json` are 404 unless `ENABLE_API_DOCS=1` (tests set it).
    Refuses to start without a `SECRET` of 32+ characters. `GET /health` (DB `SELECT 1` + whether FX rates are
    cached; 503 on failure) is what the uptime monitor and `deploy/deploy.sh` poll. `RequireAppVersion`: the iOS app
    sends `X-Zenith-App-Version`; below `MIN_IOS_APP_VERSION` (unset = off) it gets 426 `{detail, code:
    "UPDATE_REQUIRED"}` and shows a non-dismissable "Update required" screen. Requests without the header (website)
    are never affected. Keep API changes additive — old app versions stay installed for months.
  - Auth hardening: `ratelimit.py` (in-memory per-IP / per-email limits on login, register, verify and reset emails,
    login lockout, re-auth attempts; trusts `X-Real-IP` only from 127.0.0.1), `authentication/` (JWT carries
    `ver` = `user.token_version`, bumped on password reset/change, email change, first Google link and
    `POST /user/logout-all`; logins with header `X-Zenith-Client: ios-app` get 30-day tokens, the website 1 h),
    `authentication/cleanup.py` (`delete_users`; never-verified accounts older than 7 days are swept at startup and
    every 6 h). Changing email, changing password (`POST /user/password`) and `DELETE /user` need
    `current_password`. A first Google link to an existing account replaces its password (`has_password` false).
  - `db/database.py` — SQLite in WAL mode with a pool of 8; `ADDED_COLUMNS` adds columns to existing tables at
    startup (create_all only creates tables). Register every new column there.
  - `routes/assets.py` — transactions CRUD + filters (optional `created_at` to backdate; every create/edit/delete
    replays the symbol's ledger and returns 409 if history would oversell), holdings, dashboard, price/portfolio
    history, stock/crypto search (results carry `name`; query ≤ 20 chars; LRU caches; 20 new searches/min/user;
    `/prices/history` 60/min/user, both via `_check_user_rate` with Retry-After), user info/email, `DELETE /user`
    (account deletion: transactions + OAuth links + user, required by the app stores). At most 20,000 trades per
    user (`MAX_TRANSACTIONS_PER_USER`). `routes/oauth.py` — Google sign-in. `routes/analyst.py` — `GET /analyst`.
  - Trades carry an optional `account_type` (`TFSA`/`RRSP`/`FHSA`/`RESP`/`NON_REGISTERED`, null = not set; the one
    list is `AccountType`/`ACCOUNT_TYPES` in `schemas/assets.py`, `utils/accounts.js` on the frontend; `GET
    /transactions?account_type=…|UNSET`). Holdings, the ledger and the oversell check stay per symbol across accounts.
  - `routes/imports.py` + `services/imports.py` — `GET /transactions/export` (CSV of every trade, Zenith template,
    formula-injection guarded), `GET /transactions/import/template`, `POST /transactions/import/preview` (parses
    Zenith / Wealthsimple activities / Questrade activity CSVs, ≤ 2 MB / 5000 rows, flags errors and duplicates,
    saves nothing) and `POST /transactions/import` (re-validates, all-or-nothing insert, ledger replay, 409 on
    oversell); 10 of each per user per hour. Its router must be included before `user_router` in `main.py`, or
    `/transactions/{trans_id}` swallows `/transactions/export`.
  - `routes/reports.py` + `services/reports.py` — Canadian capital-gains / ACB report (`/reports/capital-gains`,
    `/years`, `.csv`): only `NON_REGISTERED`/null trades, ACB pooled per security across years in CAD (stored
    `price_of_one`), superficial-loss flags (a buy in any account within 30 days, still held), oversold sales
    flagged, never adjusted; informational 50% inclusion line; no price/FX calls.
  - `routes/allocation.py` + `services/allocation.py` — `GET /portfolio/allocation` (by asset type, account, holding,
    listing currency) priced exactly like `/holdings`; per-account quantities via `replay_accounts` (a sell takes
    from its own account, then "not set", then the largest, never negative).
  - `services/asset_services.py` — pricing (yfinance), FX conversion (open.er-api, 1 h cache; the last good rates are served if a refresh fails, 503 only with none), holdings math,
    `rebuild_symbol_ledger` (replays a symbol's buys/sells; used by PUT/DELETE to keep history valid). Ledger
    replays sort by `LEDGER_ORDER` (time, then BUY before SELL, so same-tick trades can't oversell). Every yfinance
    call goes through `run_yahoo` (own 16-thread pool, at most 6 at once); concurrent cache misses for one series
    share one fetch; FX refreshes are locked. Routes call `end_read(session)` before waiting on any price source so
    a slow provider doesn't hold one of the few DB connections — do the same in new routes.
  - `analyst/` — market analyst: `data.py` (collects data), `indicators.py` (pure maths), `engine.py` (rules →
    report), `gemini.py` (optional rewording), `service.py` (DB cache, rate limits), `schema.py` (response model).
  - `db_models/assets.py` — `User`, `Transaction`, `OAuthAccount`, `UserManager` (password rules: 8–128 chars, not
    the email, not one repeated character, not in `common_passwords.py`) and
    `send_link_email` (verification + password-reset emails via `SMTP_*`, else `GMAIL_*`, else the link is logged;
    retried twice; failure logs never include addresses). Login and re-auth hash passwords in a thread. Reset flow:
    `/auth/forgot-password` (always 202) → email → `/reset-password?token=` page (moves the token out of the address
    bar into sessionStorage, `Authentication/resetToken.js`) → `/auth/reset-password`.
- `frontend/` — React 19 + Vite + recharts. `src/services/api.js` is the only place that calls the backend
  (`request()` adds the token, maps errors to readable messages, logs out on 401/403).
  - `pages/` (one per route), `Dashboard/` (incl. the Allocation card), `Holdings/`, `Transactions/`, `Search/`,
    `Analyst/`, `Authentication/`, `Import/` (`/import`, "Import & export"), `Reports/` (`/reports`, capital gains);
    both new pages are linked under the Transactions title. CSV downloads use a text fetch in `api.js`
    (`request()` is JSON-only); in the iOS app they go through the share sheet.
    `pages/PrivacyPage.jsx` (`/privacy`, public) is the privacy policy + "not financial advice" disclaimer the app
    stores require — update it whenever the app starts collecting or sending data somewhere new. `/terms` (Terms of
    Use, incl. the CoinGecko clause its API terms require) and `/support` (App Store Connect's Support URL) share
    `components/LegalLayout.jsx` (`LegalLinks` = Privacy · Terms · Support, also under `DataCredits`); the contact
    address is `utils/contact.js`.
  - `context/UserContext.jsx` (current user + `loading`/`error`/`reload`; `currency` is null until `/user` loads, so
    nothing is formatted or cached under a guessed currency), `utils/format.js` (money/price/percent formatting — use
    `formatPrice` for asset prices so tiny coins never show $0.00; a null currency gives "—"), `utils/chart.js`,
    `utils/toast.js` (`showToast`). Quantity/price inputs are `type="text" inputMode="decimal"` and accept "1,5" or
    "1.5" (`parseDecimalInput` in `Transactions/tradeForm.js`) for comma-decimal regions.
  - CSS in `src/css/` with design tokens in `Global.css` (navy theme). Phones get a bottom tab bar (≤768px).
  - Accessibility: `components/SkipLink.jsx` ("Skip to main content") is the first Tab stop on every page; each page
    renders one `<main id="main-content" tabIndex={-1}>` as its target. On login, "Forgot password?" sits after the
    password field so Tab goes email → password.
- iOS app — Capacitor 8 wraps the same frontend (`frontend/capacitor.config.json`, Xcode project in `frontend/ios/`,
  Swift Package Manager, app id `ca.zenithwalletracker.app`). App-only code lives in `src/native/` and every part of
  it checks `isNative` first, so the website is unaffected (`test/native.test.js` guards this): Keychain copy of the
  token (cleared on a fresh install), Face ID lock (decisions in `lockRules.js`: only a quick return to an app that
  was *unlocked* skips Face ID), haptics, share sheet, pull to refresh (`useRefreshKey`), offline cache of the
  portfolio screens (`offlineCache.js`, used by `api.js`; keyed by user + currency, LRU 40), 12 s request timeout
  falling back to saved data (`connectivity.js`), native app-switcher cover in `SceneDelegate.swift` (when the lock
  is on), `@capacitor/keyboard` (accessory bar kept for its Done key; `keyboard-open` on `<html>` hides the tab bar),
  offline banner, app version header + "Update required" screen (`appVersion.js`, `updateRequired.js`,
  `UpdateRequired.jsx`), `zenithwallet://login` links from the verify/reset pages' "Open the Zenith app" button
  (`appLinks.js`, `AppLinkNavigator.jsx`; only known screens, never data from the URL), labelled tab bar without log out and with Dashboard first
  (`tabOrder.js`; the website keeps Search first) (`html.native` CSS in `Native.css`), splash/status bar, no pinch
  zoom, iOS Text Size via `@capacitor/text-zoom` (`textZoom.js`, capped at 130%, re-read on resume; tab labels stay
  fixed like a native tab bar), outside `http(s)` links opened in an in-app Safari sheet via `@capacitor/browser`
  (`externalLinks.js`, one capture-phase click listener; `mailto:` untouched). In the app `/` skips the marketing page and
  Google sign-in is hidden (web views can't use it; would also need Sign in with Apple). Backend CORS always allows
  `capacitor://localhost`.
  - Build the app with `npm run build:ios` (`vite build --mode ios` into `dist-ios/` using the committed
    `frontend/.env.ios`, drops website-only files like the demo video and fails unless the bundle has an https API
    URL, then `cap sync ios`); the website's `dist/` is separate. iOS 17+, iPhone only. Cloud builds:
    `codemagic.yaml` (no Mac needed); a pushed `ios-v<version>` tag sets the app version, the build number is bumped
    automatically. `VITE_IOS_APP_STORE_URL` (empty until the app is live) is the update screen's App Store link.
  - App Store submission: `docs/app-store.md` (listing fields, review notes, checklist); the reviewers' demo account
    is made/reset on the server with `scripts/create_demo_account.py <email> [--reset]`.
  - `ios/App/App/PrivacyInfo.xcprivacy` is Apple's privacy manifest (UserDefaults reason CA92.1, collected data
    incl. search history: not linked, 14-day server logs; check new plugins for required-reason APIs);
    keep it, the App Privacy answers and `/privacy` in step. Icons/splash come from `frontend/assets/`
    (`npx @capacitor/assets@3.0.5 generate --ios ...`, not installed: it pulls vulnerable deps).
- Fonts: Lato is bundled (`@fontsource/lato`, imported in `main.jsx`); no Google Fonts requests.
- Data credits: `components/DataCredits.jsx` under every signed-in page and "Powered by CoinGecko" on crypto search
  results are required by CoinGecko's and ExchangeRate-API's free plans; keep them.
- `tests/` — pytest (offline: network blocked, prices/FX/yfinance/HTTP stubbed, temp SQLite DB).
  `frontend/test/` — Vitest for pure utils.
- `scripts/dev.mjs`, `scripts/test-backend.mjs` — used by the root `package.json`. `deploy/` — server files
  (systemd units, backup and deploy scripts, journald config).

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
- Quantities/prices are `Numeric(20, 10)` (SQLite hands them back as floats): compare with `as_quantity` /
  `sell_tolerance`, never raw floats. Quantity max is 1e9.
- A USD/EUR trade dated more than a day back is converted to CAD at its own date's rate (Yahoo daily `USDCAD=X` /
  `EURCAD=X`, one cached series per currency, latest close known at that time; `cad_price_on` in
  `asset_services.py`) on create, edit and CSV import, falling back to the current rate when the history is missing
  — the capital-gains report needs trade-date rates. Trades saved before this keep their entry-day rate.
- Trades also keep `price_entered` + `currency_entered` (as typed). `price_in_currency` / `profit_in_currency` use
  them when the user's currency matches, so amounts never drift with FX; use these helpers for any new money sum.
- Timestamps are stored as naive UTC; filters convert offset-aware input to UTC first.
- Crypto `api_id` is the lowercase CoinGecko symbol (e.g. `btc`); search results also carry `coin_id` (`bitcoin`).
  Trades keep it too (nullable `coin_id`, sent by the add-trade form; several coins share tickers): every CoinGecko
  lookup for that holding (price fallback, portfolio chart, `/prices/history?coin_id=`) uses that exact coin, and
  holdings return it for their chart. Trades without one keep the ticker lookup (most popular coin).
- At most 200 different `api_id`s per user (`MAX_SYMBOLS_PER_USER`, 422 on create / editing onto a new asset):
  every holdings/dashboard/chart request prices each one, so this caps the Yahoo calls per request.
- Stock prices come in the listing currency (Yahoo `info.currency`, e.g. USD, CAD, EUR, `GBp` = pence) and are
  converted to CAD with `get_native_to_cad_factor` (USD cross rates, cached 1 h), then to the user's currency.
  Rows with a missing (NaN) close are skipped. An unknown listing currency is logged and the price is unavailable
  (never silently USD); with no currency from Yahoo it's guessed from the ticker suffix.
- Every price (value card, holdings, past values, portfolio chart) is "the latest close known at that time" from one
  cached history per asset (`_series_cache`): a bar counts from start + bar length (or its fetch time while live),
  never the nearest label, which could be a future close. Crypto: Yahoo `SYMBOL-CAD`, then `SYMBOL-USD`, then
  CoinGecko, everywhere. No price at all → `null` ("—" in the UI), left out of value and returns, never 0.
- `/dashboard` returns `value`, `curr_timeperiod`, `basis` (start value + buys in the period; all time = cost of
  every buy; the UI's return % = curr_timeperiod / basis) and `unpriced` (named in a note under the cards).
- `/portfolio/history` points are `{time, value, invested}`: `invested` = cost basis of what was held then (average
  cost via `apply_trade`, the same replay as the holdings, prices via `price_in_currency`), over the same priced
  holdings as `value`; the dashboard draws it as the dashed "Invested" line. Charts get a visually hidden text
  summary (`chartSummary` in `utils/chart.js`). `range` is days (1–3650) or `all` = since the first trade (the
  dashboard's "All"; never `date_joined`, which hid backdated/imported history). The dashboard loads
  `/portfolio/allocation` with each range's stats so the Allocation total matches the value card.
- Stock search uses TwelveData only for `symbol_search` (1 credit; free plan = 8 credits/min) with matches cached
  10 min per query; prices come from Yahoo (`get_latest_stock_quotes`). Don't reintroduce TwelveData `/quote`
  (1 credit per symbol): it used up the limit and errors showed as "no results". Provider errors → 503 with a message.
  US and Canadian listings are kept and mapped to Yahoo tickers with the import's helpers (`yahoo_listing`: TSX `.TO`,
  TSXV `.V`, NEO `.NE`, CSE `.CN`, `BRK.B` → `BRK-B`); results carry `exchange` + `country` (shown as
  "TSX · Shopify Inc."). A typed suffix (`SHOP.TO`) searches `SHOP` and keeps that exchange's listings.
- Money: `formatMoney` writes USD as "US$" (never a bare "$", which Canadians read as CA$).
- `/prices/history` falls back to CoinGecko for coins Yahoo doesn't list (e.g. PEPE), cached; it returns `source`,
  and `covered_range: "1Y"` + `note` for a CoinGecko "5Y" (its free plan stops at 365 days), shown under the chart.

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
  30 fresh reports per user per hour and 120 across all users (`GLOBAL_GENERATIONS_PER_HOUR`, in memory; 429 with
  Retry-After, or the older cached report). Per-asset locks are dropped once unused. No news feed is connected
  (stated in `limitations`).

## Environment (`.env` in project root; never commit it)
`SECRET`, `DATABASE_URL` (default `sqlite+aiosqlite:///./walletdatabase.db`, anchored to project root),
`FRONTEND_URL`, `BACKEND_URL` (public API URL, used for the Google callback), `API_KEY` (TwelveData),
`API_KEY_COINEGECKO` (CoinGecko demo), `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`/`EMAIL_FROM` (transactional
email provider; 465 = SSL, else STARTTLS), else `GMAIL_USER`/`GMAIL_PASS`; with neither the link is logged,
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (Google sign-in; button hidden without them), `GEMINI_API_KEY`
(+ optional `GEMINI_MODEL`, default `gemini-2.5-flash`; free tier isn't allowed for EU/UK/Swiss users — leave unset
unless billing is on), `MIN_IOS_APP_VERSION` (forced update; unset = off), `BACKUP_DIR`/`BACKUP_REMOTE` (backups).
Frontend: `frontend/.env` → `VITE_BACKEND_URL`; `frontend/.env.ios` for the app build.

## Deploying (server: `~/walletapp` as user `deploy`)
`bash deploy/deploy.sh [tag]`: first checks the tools, write access to `/var/www/html` and the `SECRET` length
(changes nothing if one fails), then backs up the DB, checks out the release, `uv sync --frozen`, builds the website into
`/var/www/html`, restarts `walletapp-backend` and waits for `/health`, rolling back to the previous commit if it
isn't healthy. One-time server setup (systemd unit with exactly one worker on 127.0.0.1, nightly backups kept 30
days, 14-day logs, uptime monitor) and restore steps: `docs/deploy.md`. nginx rate limits, security headers, log
format: `docs/nginx-hardening.md` (nginx must proxy from 127.0.0.1 so the backend sees real client IPs).

## Working notes
- Keep changes in the existing style (JSX with 4-space indent, plain CSS files per area, small comments explaining
  "why"). Don't commit `.idea/` or `__pycache__/`.
- For local manual testing without touching the real DB, run the backend with `DATABASE_URL` pointing at a scratch
  copy and `GMAIL_USER=`/`GMAIL_PASS=` so no email is sent. Don't commit `.claude/launch.json` (machine-specific).
- Never log in to production with real credentials from automation; test on localhost with test accounts.
