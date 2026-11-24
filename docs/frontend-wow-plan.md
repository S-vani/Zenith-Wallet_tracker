# Zenith frontend: the "wow" plan

Status: **plan only, nothing here is built yet.** How it fits together (layers, data, phone, testing, rollout, and a
review of the design's mistakes) is in [frontend-wow-architecture.md](frontend-wow-architecture.md). Every item has an ID (W = signature moment, T = type, C = colour,
S = screen layer, X = shared system) so items can be picked by ID later. "Web" = website, "App" = the iPhone app
(which keeps its iOS look from `NativeLook.css`; items marked App only touch that layer).

## 0. Scope: a menu, not a mandate

This is **not** a rewrite. The product keeps its structure; this is a frontend upgrade in layers, built so the heaviest
parts can be tried, measured and cut. Decisions so far: keep the dark-blue theme (richer, not replaced); add a Daylight
theme; fonts: Manrope + Fraunces, chosen from a preview; saved filter views are dropped; a remote kill switch for heavy effects is
built in from the start (the app isn't launched yet, so it ships in the very first release); Playwright is added for
browser tests. And one rule for everything: **fewer, better animations**, and **lighter on phones**.

**Three tiers (my judgement of what's most important and coolest):**

| Tier | What | Items |
|---|---|---|
| **1. Build** | The look, the one signature idea, the filters, and a few showpieces with the best effect for the cost | Palette + fonts + Daylight (T, C), Zenith light + mood (X2, X3), Transactions filters (F1 to F12 except F6), short Summit opening (W1), landing hero scene (W2, lighter on phones), circular theme reveal (W9), stress slider (W6), time machine (W5), plus a handful of micro-polish items: S8 digit flash, S11 donut hover, S13 list reorder, S16 buy/sell wash, S23 button states |
| **2. Try after Tier 1 is tested** | Cool but heavier; built behind flags so they can be switched off if they feel slow | Portfolio Terrain (W4), fan-chart scenarios (W7), shared-element navigation (W10), trade flight (W12) |
| **3. Parked** | Good ideas that can wait; stay in this file | Scroll story (W3), Wrapped (W8), command palette (W11), milestones (W13), ribbon loader (W14), the rest of the S list |

**Motion profiles by device** (one setting, `data-motion`, chosen automatically and overridable by the kill switch):

| Where | Default profile | What it means |
|---|---|---|
| Desktop website | `full` | everything in the tiers above, including the landing hero scene (WebGL) |
| **Phone, in the browser (website)** | **`lite`** | no WebGL/canvas scene, no pointer effects, no scroll-linked animation; the hero is a static gradient with a slow drift; opening is a 0.5 s fade; only transform/opacity reveals; the light is a single static layer that still follows the mood |
| **iPhone app** | **`app`** (between lite and full) | iOS-native feel and haptics; time machine, stress slider, filters and the light run at full quality; canvas pieces (Terrain, if built) run lighter (fewer bodies, lower resolution, capped frame rate, sleep when idle); **no WebGL scene, no heavy blur layers**; the opening is shortened |
| Any device with reduced motion or low-power mode | `reduced` / `lite` | stills, instant changes |

## 1. The idea that ties it together: "Zenith light"

The brand is the highest point. So the whole product gets one visual idea instead of a pile of effects:

> **A source of light at the top of the screen that reacts to your money.**

- A soft light descends from the top edge of every screen (the zenith). Its **colour and intensity are your day**:
  a teal-green tint over the navy when the portfolio is up, a muted rose-violet tint when it's down (never alarm-red),
  the normal blue when flat. Gold appears only for new highs and milestones. It always stays inside the dark-blue theme.
- It brightens on a new high, dims at night, flares briefly on a milestone, and is what the loading sequence, the
  chart line, the score ring and the buttons all pick up as their glow.
- It is the one thing people remember: *"the app that glows with how your day is going."*

Everything below either builds this light, reacts to it, or is a separate set piece with the same polish. Existing
pieces (`rise-in`, `RollingNumber`, `SegmentedThumbs`, `ChartSkeleton`, the score ring, floating preview cards,
`body::before` glow) are kept and re-skinned, not thrown away.

## 2. Guardrails (apply to every item)

1. **Calm where money is, bold where it isn't.** Set pieces live on the landing page, first load, milestones,
   transitions and the new features. Screens people check daily (holdings, transactions) stay fast and quiet.
2. **Reduced motion is a real design, not "off".** Under `prefers-reduced-motion` every set piece has a still version
   (a static glow, an instant reveal). Also respect the app's low-power mode / `prefers-reduced-data`.
3. **Only animate `transform`, `opacity`, `filter` (sparingly) and CSS variables.** No layout animation except
   `grid-template-rows` / View Transitions. 60 fps on an iPhone 12 and a mid Android is the bar.
4. **Progressive enhancement.** View Transitions need Safari 18 / Chrome 111+; scroll-driven animation needs Chrome 115+
   / Safari 26. Everything wraps in `@supports` with today's behaviour as the fallback (the app's minimum iOS is 17).
5. **Bundle budget:** no animation library. CSS first, then the browser's Web Animations API for anything scripted;
   springs come from CSS `linear()` curves generated once by a build script. Canvas/WebGL pieces are lazy-loaded and
   pause when off-screen or the tab is hidden.
6. **Accessibility and privacy stay intact:** focus rings visible, contrast AA (checked with a script, see C9), privacy
   mode still blurs amounts, nothing flashes more than 3 times a second, no data collected by cursor effects.
7. **No third-party requests.** Fonts self-hosted (as today), no CDN scripts, no tracking.

## 3. Typography (T)

**Chosen: option C, Manrope + Fraunces** (picked from a side-by-side preview of the current Lato and three candidate sets,
rendered on the new navy; the preview and the digit measurements are what this section is based on).

| Voice | Font | Used for |
|---|---|---|
| **Text and UI** | **Manrope** (variable, 200 to 800) | navigation, forms, lists, paragraphs, tickers (`AAPL`, bold, a touch of letter-spacing), **all amounts and prices** (with `tabular-nums`) |
| **Display** | **Fraunces** (variable, upright + italic) | landing headline and its italic accent word ("move"), section titles, empty states and 404, the X-Ray label and score, Wrapped, and the big dashboard value *at rest* (see the digit rule below) |

There is **no monospace font**: the preview showed monospace fonts leave wide gaps around commas and decimals
(`$12,480.00` looked like a terminal), while Manrope's tabular figures line columns up cleanly. One less font file.

**Digit rule (from the measurements):** Manrope has equal-width digits with `tabular-nums`. **Fraunces does not**, so a
number that changes digit by digit in Fraunces would jitter. The rolling dashboard value is the one place this matters.
Two ways to keep the Fraunces look there, decided with a 10-minute visual check in Phase 0:
1. *(preferred)* give each odometer digit a **fixed-width cell** (the width of the widest digit, centred), which makes any
   font behave as tabular; if the narrow "1" then looks gappy at 54 px, fall back to:
2. the big value in **Manrope bold** (tabular) and Fraunces only for the text around it.

- **T1. Self-host via Fontsource**: `@fontsource-variable/manrope` and `@fontsource-variable/fraunces`, Latin subset,
  `font-display: swap` with size-matched fallbacks so nothing jumps. Fraunces comes in several axis variants; use the
  `wght` + `opsz` (optical size) files so big headlines get the high-contrast display cut and small text stays sturdy; leave
  the `SOFT` and `WONK` axes off. Preload Manrope; Fraunces only where it is above the fold (landing headline, the
  dashboard value). Lato is removed once every screen is verified (about 60 KB saved). First-load font budget about 90 KB gz.
- **T2. Variable-font motion (small):** headline weight eases on hover, the active nav label gains weight.
- **T3. Big-number treatment:** cents smaller and dimmer; thin-space thousands separators.
- **T4. A fluid type scale** (about 7 sizes) with one letter-spacing rule, replacing the ad-hoc sizes in the CSS files.
- **App:** keeps SF Pro for navigation, large titles and list text (the iOS feel); the same Fraunces is used for the big
  value, the X-Ray score and empty states so the brand carries over. (Easy to switch to full SF if you prefer.)

## 4. Colour and depth (C)

**Direction: keep your dark-blue identity and make it richer and more dimensional. This is not a new palette.** Same
navy family, deeper and more saturated, with a few controlled accents (violet, gold) in small doses and each area of the
app nudged to a neighbouring shade.

- **C1. A richer navy ramp (same hue, about 220 degrees).** Today's `#060a12` base and grey-ish surfaces look flat. New
  ramp: base `#040813`, surfaces `#0a1327` / `#101c38` / `#17284a`, hairline borders tinted blue
  (`rgba(130,170,255,0.10)`) instead of white, text `#eaf0ff`, muted text `#9fb0d0` (bluer than today's neutral grey,
  so the whole UI reads as one colour family).
- **C2. Blue gets a range instead of being one flat value.** *Electric* `#4d8fff` (primary actions), *Sky* `#8ac4ff`
  (links, active text), *Deep* `#1f4fd1` (gradient starts, pressed states), plus *cyan* `#3dd6ff` used only as the glowing
  end of a gradient. The primary button becomes a Deep-to-Electric gradient with an inner highlight, more luminous than
  today's `#3b82f6` to `#2563eb`.
- **C3. Violet as a supporting accent, small doses.** `#7c6cff` for "intelligence" surfaces (Portfolio X-Ray, the Market
  Analyst, the command palette), as the far end of the hero gradient and as the edge of the focus glow. Never on primary
  buttons, never as a page background.
- **C4. Gold highlight `#f2c46d`, achievements only:** new highs, milestones, the X-Ray ring at 90+, the watchlist
  star, Wrapped. Rare on purpose, so it feels earned.
- **C5. Area tints: different shades of the same theme per screen.** One CSS variable (`--area-hue`) shifts the ambient
  glow, the hairline tint and the active-tab glow by a few degrees: Dashboard 220 (pure navy), Search 205 (towards
  teal-navy), Transactions 232 (indigo-navy), Holdings 212, X-Ray and Alerts 248 (violet-navy), Account 218 (slate).
  Cards and text don't change, so nothing gets harder to read; moving between tabs cross-fades the glow, which makes
  navigation feel like moving through rooms of one building.
- **C6. Profit and loss keep their meaning (green and red), retuned for the new navy:** positive `#28d98a`, negative
  `#ff5d73` (slightly warmer and less harsh than today's `#ef4444`). They stay *semantic only*. The zenith light uses
  teal-green and rose-violet *tints*, not these colours.
- **C7. Depth system:** three elevations from translucent layers + a 1px inner highlight + a hairline gradient border
  (blue fading to clear) + very light film grain (a 2 KB noise tile) so big dark areas stop looking like plastic. Cards
  also catch the zenith light: a faint brighter edge along their top. Glass (`backdrop-filter`) only on the nav bar,
  sheets and the command palette, since it's expensive.
- **C8. Themes:** **Midnight** (the improved navy, default), **Black** (OLED: only a thin glow at the top edge, which
  costs nothing on OLED), and **Daylight** (a light theme on cool paper `#f4f6fb` with navy ink and the same accents; **included**, built after
  the dark theme is stable, and switched to with the circular reveal W9). An animated "drifting hue" theme was considered and dropped (see section 10).
- **C9. Contrast gate:** `scripts/check-contrast.mjs` computes every text/background token pair for each theme and fails
  the build under WCAG AA. A palette is only "done" when it passes.

## 5. Signature moments (W): the big ones

Each lists what people see, how it's built, where, and effort (S/M/L) and wow (1 to 5).

### W1. The Summit opening (first load) · Web+App · M · wow 5
The Z mark draws itself in a single stroke on the dark screen, a beam of zenith light falls from the top edge and
"turns on" the interface: the nav rail slides up out of the light, cards rise in sequence along the light's path,
the portfolio value counts up and the aura settles to the day's mood. 1.4 s total, skippable by any tap, played once
per session (not on every route), never blocking (the screen is usable underneath), and shortened to a 0.4 s fade for
reduced motion. On the phone it plays *after* the Face ID unlock, never over the lock screen. The app's splash hands over to the
same animation so the launch feels continuous. *Built with:* SVG stroke-dashoffset, CSS variables for the light,
a single orchestrating hook (`useIntro`).

### W2. Landing hero as a living scene · Web · L · wow 5
Replace the static preview card with a full-bleed scene: a GPU-cheap mesh gradient (navy to blue to a touch of violet) (tiny WebGL fragment shader,
~3 KB, falls back to CSS gradients) that follows the cursor like a flashlight, with **a glowing price ribbon** as the
hero chart. Dragging across the ribbon scrubs it: the big number, date and a faint "memory trail" follow your finger.
Headline reveals line by line with the serif accent word ("move") italic and sliding into place; the ticker tape below
heartbeats. On touch devices the scene auto-drifts slowly (no motion-sensor permission prompt on a marketing page).

### W3. Scroll story: "Log a trade, watch everything change" · Web · L · wow 5
A pinned section where scrolling plays the product: a tilted 3D dashboard slides in, a trade is typed (fake, scripted),
the holdings list re-sorts with a FLIP animation, the chart draws a new step, the donut re-balances, the X-Ray score
ring fills from 41 to 63, and finally the Canadian tax report line appears. Done with scroll-driven animation
(`animation-timeline: view()`), CSS 3D transforms and one real component set (not a video), so it's crisp and tiny.
Fallback: the same beats trigger on intersection.

### W4. Portfolio Terrain (alive allocation) · Web+App · L · wow 5
A new dashboard view next to the donut: every holding is a **bubble** sized by value, tinted by its day change, drifting
with soft physics (a 150-line verlet simulation on canvas, no library). Drag and throw them, pinch to zoom, tap one to
open it; sectors cluster when "group by sector" is on (uses the X-Ray look-through data). A bad day makes the field
visibly heavier (bubbles sag and darken), a good day lifts it. The simulation sleeps when everything has settled (battery),
privacy mode blurs it, and every bubble also exists as an accessible list underneath. Falls back to the static treemap. It is the image people
will screenshot.

### W5. Time machine · Web+App · L · wow 5
A scrubber under the chart: drag it back through your whole history and **the entire dashboard rewinds**: value,
holdings list, allocation, X-Ray score and the zenith light all show that day, with the bubbles regrouping smoothly.
Release to spring back to "now". Needs no per-frame server calls: `GET /portfolio/history` gets an optional `detail=holdings` mode that returns, for
each chart point, every holding's quantity and value (the server already computes exactly this while building the
chart), so one request feeds the whole scrub and it stays instant and inside the rate limits.

### W6. Stress-test slider that moves the whole app · Web+App · M · wow 5
In the X-Ray, a "what if the market falls ___%" slider. Dragging it live-updates the loss, the score ring, the bubbles
(they sag), the donut and the light (cooling toward violet, desaturating); at -30% the UI gets visibly heavy, at +20%
it brightens. Uses the per-holding betas the X-Ray already computes, so no new data. Release shows the damage in plain
words ("-CA$4,532, about 9 months of your contributions").

### W7. Fan-chart scenarios · Web+App · M · wow 4
In the Market Analyst, draw the bull / base / bear ranges as **a probability cone fanning out from today's price** on the
real chart (7- and 30-day bands, from the numbers the analyst already returns), unfolding like a hand fan when the
section opens. A draggable "when" handle shows the range at any day. Replaces three text boxes with one picture.

### W8. Year in Review ("Zenith Wrapped") · Web+App · L · wow 5
A full-screen, swipeable story sequence (tap to advance, progress bars on top, like social stories): your year's
return, best and worst trade, biggest mover, most loyal holding, total contributions, your diversification journey,
and a share card (image, no dollar amounts by default so it's safe to post). Each slide has its own animated set piece
(numbers climbing, a bubble splitting, the light colour-grading to your year). Needs one aggregate endpoint built on
the existing history and ledger services (its gains cover all accounts and are labelled "not a tax figure", unlike the tax
report). Appears every December and any time from Account.

### W9. Circular-reveal theme change · Web+App · S · wow 3 (cheap, memorable)
Tapping the theme toggle floods the new theme outward from the button in a circle via the View Transitions API
(`clip-path`), with a ripple of the new light. Falls back to a 250 ms cross-fade.

### W10. Shared-element navigation · Web+App · M · wow 4
Tapping a holding or search result *becomes* its detail view: the row's logo, name and price glide into the header
while the rest of the list recedes (View Transitions with named elements; FLIP fallback). Back reverses it. Same for
trade rows into the edit sheet and the X-Ray card into the X-Ray page. This is what makes it feel like one product
instead of a set of pages.

### W11. Command palette · Web (Cmd/Ctrl-K, "/" ) + App (pull down on Search) · M · wow 4
One fluid, blurred overlay that searches *everything*: assets, your holdings, pages ("Tax report"), actions ("Add
trade", "Set alert", "Switch to Black theme"), with results morphing as you type and a live mini price on each. Results come from
local data first (pages, your holdings, watchlist, recent searches); looking up the wider market is an explicit row, not
per keystroke, because market search is rate-limited. The fastest way around the product and a very "pro" signature.

### W12. Trade confirmation that flies home · Web+App · M · wow 4
Saving a trade: the sheet collapses to a small token that arcs into the Holdings tab, the tab icon pulses with the
new count, the portfolio value ticks and the light flares once. A sell shows realized profit growing from the token as
a gold number. Replaces the plain toast + list refresh. (Existing `just-added` glow stays as the row highlight.)

### W13. Milestone moments · Web+App · S · wow 3
Rare, restrained celebrations: first trade, portfolio value thresholds (CA$10k, 25k, 50k, 100k), all-time-return thresholds
(new-all-time-high detection is deferred: it needs the full history on every load). A single gold light-burst
rising from the top edge and a one-line card, never confetti, at most once per milestone (remembered). Gold from C2.

### W14. The line that never stops (loader, empty states, 404) · Web+App · S · wow 3
One reusable animated line component ("the ribbon") used as the loader, the empty-state backdrop and the 404, where the
line climbs, stumbles off the page and the headline says "this page fell off the chart" with a button to climb back.

### W15. Motion that you can feel (haptics in the app) · App · S · wow 3
Pair the big moments with the haptics the app already has: a soft tick per digit on the score ring, a rising tick pattern
while scrubbing the time machine, a heavier thud as the stress slider passes -20% and -30%, a success pulse when a trade
lands in W12. Same animation timeline, one `haptic()` call per beat. Web gets nothing (no vibration API on iOS Safari).

## 6. Transactions: a real filter system (F)

**Problem today:** a collapsible web form with five boxes (a symbol text box, an action select, an account select and two
date inputs), one value per field, no counts, no summary, no way to save a search, and a "Reset" that didn't work on the
phone. It looks and behaves like a basic form, not a filter system. **Target:** the feel of Linear, Stripe or Airtable's
filters on desktop, and a proper native filter sheet on the phone. Backend filters stay as they are (additive).

- **F1. Smart search bar (token input).** Type `aapl`, `buy`, `tfsa`, `crypto`, `2026`, `>500`, `last 30d` and each
  recognised word turns into a coloured chip; anything unrecognised matches the symbol or name. Autocomplete suggests only
  the user's own symbols, accounts and dates. Backspace removes the last chip, `/` focuses the bar, `Esc` clears it.
- **F2. Quick-filter chips row.** `[Buy] [Sell]` | `[Stocks] [Crypto]` | the accounts that actually have trades, each with a
  count (`TFSA 14`, `RRSP 6`, `Not set 3`) | date presets `[Last 30 days] [This year] [Last year] [Tax year 2025]` |
  `[Custom…]`. Several chips in one group combine as OR, different groups as AND. Counts update live and options that
  would give zero results are dimmed.
- **F3. Advanced filter panel** (a popover on desktop, a bottom sheet on the phone): assets multi-select with search and
  logos, a date range with a calendar and presets, an amount range with a two-handle slider drawn over a histogram of
  trade sizes, the realised result for sells (gains, losses), and sort. It applies live, with no Apply button.
- **F4. Result summary bar.** "12 of 48 trades · Bought CA$8,400 · Sold CA$2,100 · Realised +CA$310" with numbers that
  tick as the filters change. This turns filtering into an answer, not just a shorter list.
- **F5. Active-filter pills** under the bar, each removable, plus "Clear all" that leaves an Undo toast.
- **F6.** *(Dropped: no saved or smart views.)*
- **F7. Filters live in the address** (`?action=BUY&acct=TFSA&from=2026-01-01`): the Back button, reloads and shared links
  all restore them, on the phone too.
- **F8. Instant, local filtering.** The list is loaded once and filtered in the browser, so chips react immediately and
  counts can be computed. Filtering therefore also works offline in the app (the offline copy is of one request).
- **F9. Animation.** Rows FLIP when the set changes (survivors slide to their new place, leavers fade and collapse,
  newcomers rise in); chips pop in and out with a spring; counts roll; the panel/sheet opens with a soft scale and
  backdrop; "Clear all" plays a short sweep. An empty result shows a small illustration, "No trades match", and
  suggests removing the single filter that excludes the most.
- **F10. Phone specifics.** A compact sticky bar under the large title (search field + a filter button with an
  active-count badge); chips scroll horizontally with edge fades and snapping; the filter sheet has a grabber and three
  heights (peek, half, full); a light haptic tick when a chip is toggled; the summary
  collapses to one line while scrolling; pull to refresh still works.
- **F11. Accessibility.** Chips are toggle buttons (`aria-pressed`), the panel is a dialog with a focus trap, the result
  count is in a live region, every control works from the keyboard, nothing relies on colour alone.
- **F12. Sort moves into the same bar** as an icon menu, replacing the separate dropdown on its own row.

## 7. Screen-by-screen layer (S): the polish that surrounds the set pieces

**Landing (Web)**
- S1. Live ticker tape (CSS marquee, pauses on hover) with real demo prices; heartbeat on the ticker you hover.
- S2. Bento feature grid: cards tilt toward the cursor (3 degrees), a spotlight gradient follows the pointer inside each,
  each plays its own 3 s loop on hover (tax report builds a table row by row, alerts bell rings, import drops a CSV).
- S3. Headline word-by-word reveal with the serif italic accent; stats row counts up when scrolled into view.
- S4. Magnetic primary button (pulls toward the cursor 6 px), conic-gradient border that rotates on hover.
- S5. FAQ accordion with `grid-template-rows` height animation and a plus that rotates to a cross.
- S6. Footer with a giant faint "ZENITH" wordmark that lights up with the cursor.

**Login / sign up (Web+App)**
- S7. The login visual becomes a mini live dashboard that reacts to typing in the form (email filled, the value
  "unlocks"). Field focus: label floats, a gradient underline sweeps in. Wrong password: a short horizontal shake +
  the card's light flashes rose. Success: the button morphs into a check, the page lifts away as the dashboard
  assembles (continues into W1). Sign up: password rules tick with a tiny pop; Terms checkbox draws its check.

**Dashboard (Web+App)**
- S8. The value ticks digit by digit with a green/rose flash on every live change; sparkline inside the period-return
  card; stat cards have a hover spotlight.
- S9. Range switch **morphs** the line between ranges (path interpolation) instead of redrawing; crosshair follows with
  a spring and a floating date chip.
- S10. Chart gets a faint "invested" fill gap highlighted on hover to show gain.
- S11. Allocation donut: segments sweep in, hovering one lifts it and dims the rest, the centre shows its name and value.
- S12. Alerts bell rings when there's something new; unread dot pulses once.

**Holdings (Web+App)**
- S13. Rows reorder with FLIP when sorting; the open panel grows via `grid-template-rows` (smooth, no jump).
- S14. A 7-day sparkline in each row; row hover shows a spotlight and the day change in a pill.
- S15. A heat-map toggle: the list becomes a treemap coloured by day change (shares code with W4).

**Transactions & add trade (Web+App)**
- S16. Buy/Sell toggle washes the whole sheet with a faint green or rose light and morphs the button label; quantity
  field validates with a springy underline; total cost counts as you type.
- S17. Delete = row collapses with a quick strike; swipe actions in the app already planned in NativeLook.

**Search & analyst (Web+App)**
- S18. Result rows slide in staggered with logos fading up; the star fills with a gold pop; the sentiment gauge needle
  swings with overshoot; key-insight cards cascade; the "bull / base / bear" rows are replaced by W7.

**X-Ray (Web+App)**
- S19. Score ring ticks to its value with tick marks and a gold shimmer when 90+; findings slide in one by one and
  the warning icons pulse once; exposure bars grow and the "via ETF" slice shows hatched.
- S20. A radar chart of five risk dimensions (concentration, volatility, drawdown, beta, crypto share) that morphs when
  you open the stress slider (W6).

**Alerts & notifications (Web+App)**
- S21. New inbox item drops in with the bell swinging; swipe to dismiss; the briefing card has a sunrise gradient.

**Account (Web+App)**
- S22. Toggles use spring physics; saving shows an inline check that draws itself; the theme picker previews the
  actual theme in a miniature of the app (live) instead of two words.

**Global feedback**
- S23. Toasts get a progress ring and slide with the light colour; buttons have loading, success and error states
  (spinner, drawn check, shake) instead of a text swap.
- S24. Skeletons share one synchronized shimmer and match the real layout exactly; empty states get small animated
  illustrations (an empty ribbon, a sleeping bell).
- S25. Offline banner slides from the light; reconnect plays a tiny "signal" pulse.

## 8. Phone parity: every animation on the iPhone too

The iPhone app keeps its iOS structure (navigation bar, tab bar, sheets from `NativeLook.css`); the new motion is layered
on top, tuned for touch, and gated by the same `data-motion` level. Phone versions of the big items:

| Item | On the phone |
|---|---|
| **W1 Summit opening** | Continues the launch splash; plays after Face ID unlock (never over the lock screen); 1.0 s; tap to skip |
| **W2 / W3 landing scene and scroll story** | Website only (the app opens to the login or the dashboard). The website's mobile layout still gets a lighter version: auto-drifting scene, no pinned 3D (stacked reveal cards instead) |
| **W4 Terrain** | Touch-native: drag and throw bubbles, pinch to zoom, tap to open; light haptic on bubble collisions, medium on pickup; sleeps when idle to save battery |
| **W5 Time machine** | A thumb-sized scrubber with pointer capture and `touch-action: pan-y`; haptic tick per month crossed; spring back on release; excluded from pull-to-refresh |
| **W6 Stress slider** | Haptic at -10, -20 and -30 percent; the screen's glow cools as you drag; release shows the damage in words |
| **W7 Fan chart** | Press-and-hold to place the "when" handle; the band follows the finger |
| **W8 Wrapped** | Tap right/left to move, hold to pause, swipe down to close, share through the iOS share sheet (amounts hidden by default) |
| **W9 Theme reveal** | Circular reveal from the toggle where View Transitions exist (iOS 18+), a cross-fade on iOS 17 |
| **W10 Shared-element navigation** | iOS 18+ View Transitions; on iOS 17 a simpler slide (the existing page transition) |
| **W11 Command palette** | A visible search button in the navigation bar (primary) and the Search tab's pull-down (secondary); never a hidden gesture only |
| **W12 Trade flight** | The saved trade arcs into the Holdings tab icon in the tab bar, which pulses; success haptic |
| **W13 Milestones** | Gold light-burst from the top of the screen + a success haptic |
| **W14 Ribbon loader / 404** | Same component |
| **F filters** | Sticky filter bar, bottom sheet with detents, haptics (section 6) |

Phone-only extras (iOS feel), all small:
- **P1.** Tab bar with a sliding pill under the active tab (spring) and icons that animate on selection.
- **P2.** Large title that collapses into the navigation bar with a blur and fade (already partly there), with the title
  text morphing rather than swapping.
- **P3.** **Pull to refresh stretches the zenith light:** as you pull, the glow at the top stretches and brightens, then
  settles when the data lands. It ties the existing gesture to the signature idea.
- **P4.** Long-press context menus on holdings and trades (blurred backdrop, scale-up preview).
- **P5.** Swipe actions on rows (edit, delete, alert) with haptic detents.
- **P6.** Sheets with real detents and rubber-banding (generalising the add-trade sheet's drag).
- **P7.** Designed for 60 fps and time-based, so a 120 Hz web view also looks right; safe areas respected, nothing animates
  behind the keyboard, primary actions in the lower half (thumb reach).

## 9. Shared systems (X): build once, used everywhere

- **X0. Token migration (prerequisite for everything colour-related):** the CSS has many hard-coded hex values and
  gradients (`#050e1c`, `#0b1220`, ad-hoc greys). They move into the token layers first, and a lint rule bans raw hex
  outside the tokens folder; otherwise themes, area tints and the new palette silently miss places.
- **X1. Motion tokens:** durations (120 / 220 / 380 / 700 ms), easings including real spring curves via CSS `linear()`
  (`--spring-soft`, `--spring-snappy`), and a stagger helper (`--i` index variable). One file, replaces ad-hoc values.
- **X2. `useMood()`:** one hook/store that turns today's portfolio change and the market's into `{hue, intensity}`,
  written to CSS variables on `<html>`; the zenith light and every glow read it. Smoothed so it never flickers.
- **X3. `<ZenithLight/>`:** the fixed layer (two gradients, one blurred, `will-change: transform`) replacing
  `body::before`; pauses when the tab is hidden.
- **X4. View Transition helper:** `startTransition(name, update)` wrapper with named-element conventions and the
  fallback; used by W9, W10, W12 and route changes.
- **X5. Reveal system:** `data-reveal` attribute + one IntersectionObserver / scroll-timeline, replacing per-component
  fade code; variants: rise, fade, scale, draw, count.
- **X6. Pointer effects:** one passive `pointermove` listener setting `--mx/--my` on hovered cards (spotlight, tilt,
  magnetic) so no per-card JS; disabled on touch and reduced motion.
- **X7. Canvas kit:** a tiny shared render loop (one `requestAnimationFrame`, visibility + intersection pausing, DPR cap
  2, frame-time watchdog that drops quality on slow devices) used by W2 (shader), W4 (physics), W13 (burst).
- **X8. Number component:** a single `<Num>` for money (mono, tabular, small cents, tick flash, privacy blur) so every
  amount in the product looks identical.
- **X11. One motion level:** a single `data-motion="full|lite|reduced"` attribute on `<html>` set by JS from the OS
  setting, low-power mode, device capability and the frame watchdog; all effects read it (CSS defaults to the OS media
  query when JS hasn't run). One source of truth, never upgraded back from `reduced`.
- **X9. Perf and a11y tests:** a Playwright script that records long tasks and layout shifts on the landing page and
  dashboard, and a reduced-motion run that screenshots every screen. Becomes a pre-release check.
- **X10. Ambient browser chrome:** the favicon shows a small up or down arrow in the day's colour, and `theme-color` /
  the iOS status-bar background follow the zenith light, so even a pinned tab or the address bar carries the mood.
  Cheap and distinctive.

## 10. Ideas considered and rejected

- **Sound effects / music:** annoying on a finance tool, App Review friction, battery.
- **Confetti on every trade or profit:** cheapens milestones and feels like gambling UI, which we want to avoid for a
  financial product (and for Apple review). Milestones use the single gold burst (W13), rarely.
- **Scroll-jacking the whole landing page:** breaks scroll expectations, accessibility, and mobile Safari. W3 pins only
  one section and never traps the user.
- **Parallax / 3D on holdings or transactions:** data screens must stay fast and legible.
- **A WebGL globe or fake "live users" counter:** gimmicky and untrue to what the product does.
- **Cursor trail / custom cursor everywhere:** distracting; only subtle spotlight effects remain.
- **Lottie animations:** 150 KB+ runtime, hard to theme; hand-built SVG/CSS instead.
- **Autoplay background video on the landing page:** weight, battery, motion sickness; the live scene replaces it.
- **Animating the real chart's every point on each live update:** distracting and costly; only the last point pulses.
- **Typewriter text for numbers:** reads as a delay; digit ticking (S8) conveys change better.
- **Pure bright red for losses:** punishing and screams alarm; the retuned `#ff5d73` (C6) keeps meaning without the panic.
- **An animated "drifting hue" Aurora theme:** a gimmick that fights the calm blue identity and burns battery.
- **"Market weather" strip (cut in review):** weak information, extra market-data calls on every load; the zenith light
  already shows the mood without a widget.
- **Device-tilt parallax on the landing page:** needs a motion-sensor permission prompt on iOS, which feels invasive on
  a marketing page; slow auto-drift instead.
- **Neon / cyberpunk styling:** looks crypto-casino; the palette stays deep navy with restrained violet and gold.

## 11. Risks and how each is handled

| Risk | Handling |
|---|---|
| Heavy effects hurt older phones / battery | Frame-time watchdog in the canvas kit (X7) lowers quality, then falls back to the CSS version; effects pause off-screen and in hidden tabs; low-power mode gets the still versions |
| Too much motion makes a finance tool feel like a toy | Guardrail 1: set pieces only on landing, first load, milestones, transitions and new features; daily screens stay quiet |
| Safari / Firefox gaps for View Transitions and scroll-driven animation | `@supports` fallbacks keep today's behaviour; verified on iOS 17, 18, 26 simulators or TestFlight |
| New fonts cause layout jumps or slow first paint | Size-adjusted fallbacks, preload of the two critical files, subsetting; measured with the perf run (X9) |
| New palette fails contrast | The contrast gate (C9) fails the build; the retuned green/red are checked against the actual surfaces, not in isolation |
| App Review concerns | No motion changes what the app does; nothing flashes; reduced motion honoured; privacy policy unaffected (no new data, no third parties) |
| Scope creep: this is a lot | Phases are independent; each ends shippable. Anything not picked stays in this file |

## 12. Suggested order (and what each phase buys)

Each phase ends shippable and is tested on a real iPhone before the next starts. After Phase 3 you test and decide what
to cut and whether to try Tier 2.

| Phase | Contents | Why | Effort |
|---|---|---|---|
| **0. Foundations** | token migration (X0), fonts (T1 to T4), palette and area tints (C1 to C7), contrast gate (C9), motion level + profiles (X11), kill switch, Playwright, baselines | Everything inherits the new look; fonts + palette alone change the feel; the safety nets exist before any heavy effect | M |
| **1. Transactions filters** | F1 to F5, F7 to F12 | The part you flagged as too basic; independent, so it can ship first | M |
| **2. The signature** | Zenith light + mood (X2, X3), short Summit opening (W1), landing hero scene (W2, lite on phones), Daylight theme + circular reveal (W9), micro-polish (S8, S11, S13, S16, S23) | The look people remember, in the smallest set of effects | L |
| **3. Showpieces** | stress slider (W6), time machine (W5), haptics for them in the app (W15) | Best wow-per-effort features for investors; cheap on the phone because they're drag-driven and mostly numbers | L |
| **4. Optional, after you test** | Terrain (W4), fan chart (W7), shared-element navigation (W10), trade flight (W12), each behind a flag | Heavier or fiddlier; only the ones that feel good and fast stay | L |
| **Parked** | W3, W8, W11, W13, W14, remaining S | Stay in this file for later | |

## 13. Decisions

**Settled:** fonts are Manrope + Fraunces (section 3); Daylight is included; the kill switch is built in from the start,
with lighter profiles for phones; saved filter views are dropped; Playwright is added; only the most important effects are
built first, and heavy ones are flagged so they can be cut.

**Still open:**
- **D1. Loss colour:** the new red is slightly softer (`#ff5d73` instead of `#ef4444`). Fine, or keep the exact old red?
- **D2. Backend:** the time machine needs one small additive change (`/portfolio/history` gets a `detail=holdings` option).
  OK? (Wrapped's endpoint is parked.)
