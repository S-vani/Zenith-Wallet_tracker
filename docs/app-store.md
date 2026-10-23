# App Store submission checklist

## Before every submission

- [ ] API deployed and healthy (`https://api.zenithwalletracker.ca/health`).
- [ ] Demo account reset on the server:
      `.venv/bin/python scripts/create_demo_account.py appreview@zenithwalletracker.ca --reset`
      (a reviewer may have deleted it, changed its password or logged out everywhere last time).
- [ ] Sign in with the demo account in the TestFlight build; dashboard, holdings and charts show data.
- [ ] `https://zenithwalletracker.ca/support`, `/privacy` and `/terms` load.

## App Store Connect

| Field | Value |
|---|---|
| Name | Zenith: Portfolio Tracker (avoid "Wallet": the app holds no funds, and reviewers apply stricter rules to wallets) |
| Subtitle | Stock & crypto portfolio tracker |
| Category | Finance |
| Support URL | https://zenithwalletracker.ca/support |
| Marketing URL | https://zenithwalletracker.ca |
| Privacy Policy URL | https://zenithwalletracker.ca/privacy |
| Copyright | 2026 *your legal name* |
| Age rating | Answer the questionnaire honestly (no objectionable content); the privacy policy says the app isn't meant for children under 13, so don't market it to them |
| App Privacy | Must match `frontend/ios/App/App/PrivacyInfo.xcprivacy`: Name, Email, User ID, Other Financial Info (linked to the user, App Functionality, not tracking); Search History (not linked, App Functionality). No tracking. |
| Screenshots | iPhone 6.9" (1320×2868 or 1290×2796), taken in the simulator signed in to the demo account |

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
> Native features: Face ID app lock (Account → Security), Keychain storage of the sign-in, haptics, the iOS share
> sheet (Share on a search result), offline mode with saved portfolio screens and an offline banner, pull to refresh,
> iOS Text Size support, in-app Safari for outside links.
>
> Account deletion: Account tab → Delete account (type DELETE and the password). If you test it, please create a new
> account for it instead of deleting the demo account. New accounts need email verification; the link opens a web
> page with an "Open the Zenith app" button.

## Still open (not code)

- Market data licences: Yahoo Finance (via yfinance), TwelveData's free plan and CoinGecko's Demo plan don't allow
  display in a public app. Move to licensed providers before or soon after launch (deliberately left out of the
  launch work).
- A home-screen widget (WidgetKit) would further reduce the "repackaged website" (4.2) risk; it needs a Mac and an
  App Group to build.
- Universal Links instead of the custom `zenithwallet://` scheme need your Apple Team ID for the
  `apple-app-site-association` file.
