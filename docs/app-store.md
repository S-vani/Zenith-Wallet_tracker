# App Store submission checklist

## Before every submission

- [ ] API deployed and healthy (`https://api.zenithwalletracker.ca/health`).
- [ ] Demo account reset on the server:
      `.venv/bin/python scripts/create_demo_account.py appreview@zenithwalletracker.ca --reset`
      (a reviewer may have deleted it, changed its password or logged out everywhere last time).
- [ ] Sign in with the demo account in the TestFlight build; dashboard, holdings and charts show data.
- [ ] On production with the demo account: search "BTC" (crypto) and "AAPL" (stock), open one analyst report. A
      reviewer seeing a search error is a classic 2.1 rejection.
- [ ] `https://zenithwalletracker.ca/support`, `/privacy` and `/terms` load.
- [ ] Don't deploy while the app is in review (a restart clears login lockouts, but a broken deploy would be seen).
- [ ] Decided whether the app is available on Apple-silicon Macs (App Store Connect → Pricing and Availability).

The demo account's email must use a real domain: sign-up and password reset reject reserved test domains such as
`.test`. No email is ever sent to it, so it doesn't need to be a real inbox.

## App Store Connect

| Field | Value |
|---|---|
| Name | Zenith: Portfolio Tracker (avoid "Wallet": the app holds no funds, and reviewers apply stricter rules to wallets) |
| Subtitle | Track stocks & crypto trades (28 characters; the limit is 30) |
| Category | Finance |
| Support URL | https://zenithwalletracker.ca/support |
| Marketing URL | https://zenithwalletracker.ca |
| Privacy Policy URL | https://zenithwalletracker.ca/privacy |
| Copyright | 2026 *your legal name* |
| Age rating | Answer the questionnaire honestly (no objectionable content, no unrestricted web access: outside links open specific pages in a Safari sheet), then choose **13+** so it matches the Terms and privacy policy (not meant for children under 13) |
| App Privacy | Must match `frontend/ios/App/App/PrivacyInfo.xcprivacy`: Name, Email, User ID, Other Financial Info (linked to the user, App Functionality, not tracking); Search History (not linked, App Functionality). No tracking. |
| Screenshots | iPhone 6.9" (1320×2868) and 6.3" (1206×2622, iPhone 17 Pro simulator), signed in to the demo account, showing the app in use (not the login screen) |

Description must say plainly: manual record-keeping only; it does not connect to banks, brokers or exchanges, hold
or move money, execute trades, or give financial advice.

## App Review notes (paste and adjust)

> Zenith is a portfolio tracker: users record their own stock and crypto trades by hand and see holdings, value and
> returns over time. It does not connect to any bank, broker or exchange, never holds or moves money, and does not
> execute trades. The "Market analyst" is an automated, rules-based summary of public market data and is labelled
> "not financial advice".
>
> Demo account (already verified, with sample trades): *email* / *password*
>
> Native features:
> - Siri and Shortcuts (App Shortcuts, no setup needed): "What's my portfolio worth in Zenith" answers with the
>   value and today's change without opening the app; "Add a trade in Zenith", "Open my Zenith dashboard", "Show my
>   Zenith holdings" and "Search in Zenith" open those screens. They also appear in Spotlight, the Shortcuts app and
>   on the Action button. Open the dashboard once after signing in so the value is available.
> - Home Screen quick actions: press and hold the app icon for Add Trade, Search, Holdings and Dashboard.
> - Face ID app lock (Account → Security; the card appears when the device has Face ID or a passcode set up). While
>   it's on, Siri doesn't read out the value, and the app switcher shows a cover instead of the portfolio.
> - Offline mode: turn on Airplane Mode and reopen Dashboard or Holdings; saved data shows under a "You're
>   offline" banner.
> - CSV export and the tax report's CSV go through the iOS share sheet as real .csv files (Save to Files, Mail).
> - Keychain storage of the sign-in, haptics, the share sheet for search results (Search → select a result →
>   "Share <TICKER>"), pull to refresh, iOS Text Size support, in-app Safari for outside links.
>
> The analyst's scenario ranges are historical-volatility ranges, not price targets, and the app says so next to
> them. Its text is written by built-in rules; when an optional AI service is enabled it only rewords the same
> numbers, and the report then shows an "AI-written" badge. The server can show an "Update required" screen to very
> old app versions if the API ever changes incompatibly.
>
> Other features: CSV import of trades from Wealthsimple or Questrade exports (with a preview before saving), CSV
> export of all trades, an allocation breakdown and a Canadian capital-gains report (both clearly labelled as not tax
> or financial advice).
>
> Account deletion: Account tab → Delete account (type DELETE and the password). If you test it, please create a new
> account for it instead of deleting the demo account. New accounts need email verification sent to a real inbox
> (from our sender address; check spam); the link opens a web page with an "Open the Zenith app" button.

## Still open (not code)

- Market data licences: Yahoo Finance (via yfinance), TwelveData's free plan and CoinGecko's Demo plan don't allow
  display in a public app. Move to licensed providers before or soon after launch (deliberately left out of the
  launch work).
- A home-screen widget (WidgetKit) would further reduce the "repackaged website" (4.2) risk. It's a separate
  extension target with its own bundle id and an App Group (enabled on both ids in the Apple Developer portal, plus
  a second provisioning profile in Codemagic), so it's left for later; Siri / Shortcuts and the quick actions cover
  4.2 without that setup.
- After approval: set `VITE_IOS_APP_STORE_URL` in `frontend/.env.ios` (the "Update required" screen's link) **and**
  in the website's `frontend/.env` on the server, then deploy: the "Open the Zenith app" button on the verify and
  reset-password pages only shows once it's set (before release it led nowhere).
- Universal Links instead of the custom `zenithwallet://` scheme need your Apple Team ID for the
  `apple-app-site-association` file.
