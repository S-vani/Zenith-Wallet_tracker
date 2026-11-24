# Architecture for the "wow" plan

Companion to [frontend-wow-plan.md](frontend-wow-plan.md) (the *what*). This is the *how it fits together*: layers,
folders, state, data, performance, phone, testing and rollout. **No code yet.** IDs (W, S, F, X, C, T, P) refer to the
plan. Section 15 records the mistakes found while analysing this design and where each fix is written in.

**Scope note.** Only the Tier 1 items of the plan are built first (plan section 0). From this document that means
sections 3 to 7 (tokens, fonts, motion level, state, the light), 8.1 (opening), 8.2 (landing hero only), 8.4 and 8.5
(time machine and stress slider), 8.11 (filters), 9 to 13. The designs for Terrain, the fan chart, shared-element
navigation, trade flight, Wrapped, the command palette and milestones are kept here as design notes for later tiers.
Decisions since the first draft: saved filter views are dropped, Daylight is included, the kill switch is built in from
the start, and phones get lighter motion profiles (section 5.1).

## 0. Starting point (facts from the current code)

- React 19 + Vite, plain CSS files per area, React Router 7 (`BrowserRouter`), recharts for charts, Capacitor 8 wraps
  the same build for iOS (iOS 17+ web view). The app-only layer is `html.native` CSS (`Native.css`, `NativeLook.css`)
  and `src/native/*` modules that check `isNative` first.
- **About 228 hard-coded hex colours** are spread across the CSS files. There is no token system beyond a few variables
  in `Global.css`.
- Motion today: a few keyframes (`rise-in`, `sheet-in`, `draw`, `score-fill`, ...), `RollingNumber`, `SegmentedThumbs`,
  `ChartSkeleton`, `PageTransition` (app only), `PullToRefresh`, `useSheetDrag`. Reduced motion is one global CSS rule.
- Tests: Vitest runs in the **node** environment (no DOM), so only pure logic is unit-testable today. Playwright has
  only been used ad hoc from scratch scripts, not in the repo.
- The marketing page is part of the client-rendered SPA; `index.html` already carries the SEO tags and a static title.
- Data already available for the new features: `/holdings` (now with `day_change_pct`), `/dashboard`,
  `/portfolio/history`, `/portfolio/allocation`, `/portfolio/xray` (score, exposure, per-holding betas, stress tests),
  `/analyst` (bull/base/bear ranges), `/transactions` (all trades, filters server-side), notifications.

## 1. Principles

1. **Layers only point downward.** Tokens know nothing; motion primitives know tokens; UI primitives know motion;
   features know primitives; pages know features. No feature reaches into another feature.
2. **Pure logic is separate from DOM code**, so it can be tested in the node-only Vitest setup (filter model, physics,
   mood mapping, motion-level decision, easing generator, query parser, FLIP maths).
3. **One source of truth per concern:** one mood store, one motion level, one theme attribute, one gesture registry, one
   view-transition helper, one render loop for canvases.
4. **Everything has a fallback.** Features are written as enhancements over the current behaviour, never replacements
   that can fail visibly.
5. **Platform is a layer, not a fork.** The same components run on web and in the app; phone-specific behaviour is added
   by the platform layer (`native/`), capability checks, and `html.native` CSS, as it is today.
6. **Measure before and after.** Baselines are recorded first (section 11); every phase must stay inside budget.

## 2. Layer model and folder map

```
frontend/src/
  design/                 LAYER 0: tokens, themes, type, motion tokens. CSS only, no JS logic
    tokens/               primitive.css (raw ramps), semantic.css (--surface-1, --text-muted, --accent...),
                          component.css (--card-bg, --btn-primary-bg...)
    themes/               midnight.css, black.css, daylight.css (override semantic tokens only)
    areas.css             --area-hue per [data-area]
    type.css              font-faces, type scale, numeric rules
    motion.css            durations, easings, spring curves (generated), data-motion switches
    depth.css             elevation, grain, hairline borders, light-catching edges
  motion/                 LAYER 1: motion + effects infrastructure (JS)
    motionLevel.js        decides full | lite | reduced; writes <html data-motion>   (X11)
    mood.js               the mood store + mapping from stats to {hue, intensity}    (X2)
    ZenithLight.jsx       the fixed light layer                                      (X3)
    viewTransition.js     named-element helper + fallback                            (X4)
    reveal.js             data-reveal observer / scroll-timeline wrapper             (X5)
    pointerFx.js          one pointer listener setting --mx/--my                     (X6)
    canvasKit/            scheduler.js, visibility.js, watchdog.js, dpr.js           (X7)
    haptics.js            beat-name -> native haptic mapping with throttling         (P / W15)
    gestures/             useDrag.js, registry.js (who owns which touch)
    flip.js               measure/animate helper for list reorders and shared moves
  ui/                     LAYER 2: reusable primitives (no business logic)
    Num/  Button/  Chip/  Popover/  Sheet/  Segmented/  Skeleton/  Toast/  Ring/  Ribbon/
  features/               LAYER 3: one folder per feature, each self-contained
    intro/  landing/  terrain/  timemachine/  stress/  fan/  wrapped/  palette/
    tradeflight/  milestones/  filters/
  pages/                  LAYER 4: routes compose features (as today)
  native/                 platform layer (exists): push, biometric, lock, haptics (native side), screens
  utils/  services/       exist (api.js stays the only place that calls the backend)
```

Migration rule: existing components move into `ui/` or `features/` only when they are touched; there is no big-bang
move. `components/` keeps working in the meantime.

## 3. Design tokens, themes, area tints, mood

### 3.1 Three token layers
- **Primitive** (raw values): the navy ramp, blue range, violet, gold, P&L hues. Never used directly in components.
- **Semantic** (meaning): `--bg`, `--surface-1/2/3`, `--border`, `--text`, `--text-muted`, `--accent`, `--accent-text`,
  `--positive`, `--negative`, `--highlight`. **Themes override only this layer.**
- **Component** (specific): `--card-bg`, `--btn-primary-bg`, `--chip-bg`, `--sheet-bg`. Components use only semantic and
  component tokens.
- Existing variables (`--card-bg`, `--accent-solid`, `--ease-out`...) keep their names so current CSS keeps working
  during migration; they become aliases of the new layers.

### 3.2 Theme and area selection
- `<html data-theme="midnight|black|daylight">`. Today's `appTheme` storage key and `appearance.js` are extended to the
  web; the default is Midnight. Applied by a tiny inline script in `index.html` *before first paint* (no flash).
- `<main data-area="dashboard|search|transactions|holdings|xray|account">` set by the layout from the route; it only
  sets `--area-hue`. Tints change glow, hairlines and active-tab glow, never card or text colours (readability safe).

### 3.3 Mood (the zenith light's input)
- One store (`mood.js`): `{hue, intensity, source, at}`. The Dashboard publishes it from today's change; every other
  page reads it. Mapping (pure, unit-tested): up gives teal-green tint, down gives rose-violet tint, flat gives
  blue; intensity scales with the size of the move and is capped.
- **Persisted** (last value + time) and applied by the same inline script before first paint, so other screens and cold
  starts don't flash neutral. A value older than about 18 hours decays to neutral blue.
- **Privacy mode forces neutral**, because a coloured glow would leak up/down in public.
- Logged-out pages (landing, login) use a fixed demo mood.
- CSS interpolation of colours through custom properties only works if the properties are registered with `@property`
  (syntax `<color>` / `<number>`); otherwise changes snap. Both hue and intensity are registered, and the glow uses
  `hsl(var(--hue) ...)`. Fallback: crossfade two layers with `opacity`.

### 3.4 Migration and enforcement (X0)
1. Add the three token layers and aliases (no visual change).
2. Replace hard-coded hex in the CSS files area by area (Global, Dashboard, Holdings, Transaction, Search, Analyst,
   User, Home, Login/Signup, Native/NativeLook).
3. Add a lint rule (stylelint `color-no-hex` outside `design/tokens`) so it can't regress.
4. Only then change the palette values (one-file change), and add Daylight.
5. `scripts/check-contrast.mjs` (C9) runs in CI for every theme.

## 4. Typography

- Two families (plan section 3): **Manrope** (UI, tickers, all amounts) and **Fraunces** (display), self-hosted through
  Fontsource as variable files, Latin subset. No monospace font.
- `font-display: swap` plus **size-adjusted fallback faces** (`size-adjust`, `ascent-override`) so swapping doesn't shift
  layout. Manrope is preloaded; Fraunces (the `wght` + `opsz` files, upright and italic) is preloaded only on routes where it is
  above the fold (landing headline, dashboard value) and otherwise loads on demand.
- Numeric rules live in `type.css`: all amounts and quantities use Manrope with `tabular-nums`. **Fraunces has no tabular
  figures (measured), so the odometer (`RollingNumber`) gives every digit a fixed-width cell** (the widest digit's width,
  centred); if that looks uneven at display size, the one animated number falls back to Manrope bold (decided by a quick
  visual check in Phase 0). Any other number that changes digit by digit follows the same rule.
- The app keeps SF Pro for navigation, large titles and lists; Fraunces appears only in the big-value, score and
  empty-state components.
- Removing Lato is the last step, after every screen is verified in the new stack.

## 5. Motion system

### 5.1 One motion level (X11)
`motionLevel.js` computes `full`, `lite` or `reduced` from: the OS reduced-motion setting, iOS low-power mode (via
the native layer in the app), `navigator.hardwareConcurrency` / `deviceMemory`, and the runtime frame watchdog. It writes
`<html data-motion>` and emits an event. Rules: precedence is `reduced` > `lite` > `full`; it never goes back up once
lowered in a session; CSS defaults to the OS media query when JS hasn't run. Every effect asks "what level am I?", not
"is the media query on?". Behaviour by level:

| Level | Behaviour |
|---|---|
| `full` | everything in the plan |
| `lite` | no canvas/WebGL, no blur-heavy layers, no pointer effects, simpler transitions, still has the zenith light (static) |
| `reduced` | no movement; instant state changes; static glow; fades under 150 ms only |

### 5.1b Default level by platform (the phone rule)
The level is chosen per device class at startup and can only be lowered afterwards (by the user's OS setting, the
watchdog, or the kill switch):

| Device | Default | Heavy effects (WebGL scene, canvas physics, backdrop blur layers, pointer effects, scroll-linked animation) |
|---|---|---|
| Desktop website | `full` | allowed |
| Phone website (narrow, `hover: none`) | `lite` | **all off**; reveals use transform/opacity only; one static light layer |
| iPhone app | `app` (a `full` variant) | no WebGL scene, no stacked blur; canvas pieces at reduced resolution and a frame cap; drag-driven features (time machine, stress slider, filters) at full quality |

Each feature declares the lowest level it needs and its lighter variant (for example Terrain: `app` = fewer bodies,
resolution cap, sleeps when idle; `lite` = the DOM list only). The kill switch (section 10) can force any device down to
`lite` or `reduced` without a release.

### 5.2 Tokens and springs (X1)
Durations (120 / 220 / 380 / 700 ms), easings, and 3 spring curves expressed as CSS `linear()` strings **generated once**
by a script from spring parameters (so they are real physics, not guesses) into `design/motion.css`. No animation
library. Scripted animation uses the browser's Web Animations API (`element.animate`), which is promise-based, so
sequences await `finished` instead of chaining timeouts.

### 5.3 Reveal system (X5)
`data-reveal="rise|fade|scale|draw|count"` plus optional `data-reveal-delay`. One shared IntersectionObserver
singleton adds a class once; where `animation-timeline: view()` is supported it is used for scroll-linked reveals instead.
Replaces per-component fade code. Initial states are applied by CSS, so there is no flash of unrevealed content when JS
is late (the content simply appears if the observer never runs).

### 5.4 View transitions (X4)
Use React Router 7's built-in `viewTransition` support for route changes; a thin helper handles non-route
transitions (theme reveal, sheet to row). Rules that avoid the known pitfalls:
- A transition name may exist on **one element at a time**, so list rows are *not* pre-named; the helper names only the
  clicked row right before navigating and removes the name after.
- Persistent chrome (navigation bar, tab bar, the zenith light) gets fixed names so it doesn't cross-fade with content.
- On the phone the existing `PageTransition` (CSS page-enter) is disabled when View Transitions run, so they don't stack.
- Capability check first (`document.startViewTransition`); otherwise today's behaviour, unchanged.

### 5.5 Pointer effects (X6)
One passive `pointermove` listener on the document writes `--mx/--my` to the hovered element marked
`data-spotlight|data-tilt|data-magnet`; the effects themselves are pure CSS. Disabled on touch, `lite` and `reduced`.

### 5.6 Haptics bridge
`motion/haptics.js` maps beat names (`tick`, `soft`, `thud`, `success`) to the native plugin and **throttles** (minimum
about 40 ms between calls, maximum burst) so scrubbing can't buzz continuously. Web: no-op. Animations that need
haptics call the bridge at their key frames from the same WAAPI timeline.

## 6. State and data flow

| Store / hook | Owner | Consumers | Persistence |
|---|---|---|---|
| `mood` | Dashboard publishes | `ZenithLight`, favicon/theme-color (X10), cards' top-edge light | localStorage (value + time) |
| `motionLevel` | `motionLevel.js` | all effects | none (recomputed per session) |
| `theme`, `area` | settings / route layout | CSS only | theme in localStorage |
| `transactions` | `useTransactions()` | Transactions page, filters, command palette, Wrapped | in-memory cache + offline cache of the one request |
| `history+holdings` | `useHistoryDetail()` | time machine, terrain scrub | in-memory only (see 8.4 about the offline cache) |
| `xray` | existing | stress slider, terrain grouping, dashboard card | existing 30-min server cache |
| `milestones seen` | `milestones.js` | milestone moments | localStorage |

State management stays hooks + small external stores (`useSyncExternalStore`); no new state library.

## 7. Canvas and WebGL kit (X7)

Used by the landing scene (shader), Terrain (2D physics) and the milestone burst. Shared rules:
- **One scheduler** owns a single `requestAnimationFrame` loop; effects register `update(dt)` / `draw()`; time-based (not
  frame-based), so 60 or 120 Hz both look right.
- Pauses when the canvas is off-screen (IntersectionObserver), the tab is hidden, or the level is not `full`.
- Device-pixel ratio capped at 2; canvas resolution adapts to a frame-time budget; the **watchdog** drops resolution,
  then switches the effect to its static fallback, then lowers `data-motion` to `lite` if the whole page is struggling.
- WebGL context loss is handled (restore or fall back); a CSS gradient is always painted first, so there is never a blank.
- Each canvas feature has a **DOM twin** for accessibility and fallback (an ordinary list with the same information).
- Lazy-loaded chunks: shader ≤ 8 KB gz, Terrain ≤ 25 KB gz.

## 8. Feature architectures

### 8.1 Intro / boot sequence (W1)
A small state machine in `features/intro`: `splash -> locked? -> intro -> idle`.
- Web: no splash; the intro plays once per session on the first dashboard or landing load; never blocks input (it is a
  non-interactive overlay above content that is already usable); any tap or key ends it.
- App: the native splash hands off after first render (as today). If the Face ID lock is on, the intro waits for a new
  `app:unlocked` event from `AppLock` (a small addition) and then plays; otherwise it plays immediately. `reduced`: a 0.4 s
  fade.
- The Z-mark stroke animation is one inline SVG; the light descent and card stagger use `data-reveal` and the light layer,
  so the intro is mostly the normal reveal system run slightly earlier.

### 8.2 Landing scene and scroll story (W2, W3, S1 to S6)
- The hero paints **instantly** from CSS (gradient + headline + static ribbon). The shader scene is a lazy chunk mounted
  after idle on capable devices; it replaces nothing visible until ready (cross-fade).
- Scroll story: a pinned `section` driven by `animation-timeline: view()` / `scroll()` on supported browsers; elsewhere
  the same beats are triggered by intersection with simple state changes. The "product" shown is real, small components
  fed by scripted fake data (a `demoData` module), not a video. Mobile layout: stacked, unpinned.
- SEO and LCP: `index.html` already carries meta; the hero text is in the first chunk. Pre-rendering the landing HTML at
  build time is an optional later step (see section 15, item 13).

### 8.3 Portfolio Terrain (W4)
- `physics.js` (pure): bodies with radius from value, soft collisions, gentle central pull, optional sector clustering
  (using the X-Ray look-through sectors), drag/throw, settle detection. Unit-tested.
- `TerrainCanvas.jsx`: draws bodies (logo/initials, ticker, day change tint) and handles pointer events through the
  gesture registry.
- `TerrainList.jsx`: the **DOM twin** (screen-reader and keyboard accessible list sorted by value) shown in `lite` /
  `reduced`, for assistive tech, and inside the page for keyboard focus; selecting an item opens the holding.
- Energy: the simulation **sleeps** when bodies settle and wakes on touch or data change. Privacy mode blurs the canvas
  element (CSS `filter`), because canvas text isn't affected by the normal amount selectors.
- Data: `/holdings` + `/portfolio/xray` (sector grouping), both already loaded elsewhere.

### 8.4 Time machine (W5)
- Backend: `GET /portfolio/history` gains `detail=holdings`. Each point also carries the holdings at that time as
  `{symbol: {quantity, value}}`, limited to the user's top 40 holdings by current value plus one "rest" bucket to cap
  the payload (a few hundred points x 40 holdings compresses to tens of KB).
- Frontend: `useHistoryDetail(range)` fetches once; `timemachine/` turns the pointer position into an index, then a
  `viewModel` (value, holdings, allocation) for that index. The dashboard components accept an optional "as of" view model
  and render it without refetching. Scrubbing sets one CSS variable and one React state update per frame at most.
- These responses are **excluded from the offline persisted cache** (size), but cached in memory.
- Gesture: the scrubber registers as an owner of horizontal touch (`touch-action: pan-y`, pointer capture) so pull to
  refresh and page scroll don't fight it.

### 8.5 Stress slider (W6)
Pure client calculation from the X-Ray payload (per-holding weights and betas, already returned). Output: new value,
loss in money and percent, per-holding contribution. It drives three consumers: the numbers, the terrain bodies' sag and
the light's hue/intensity (through a *temporary* override of the mood store that is released on close). Labelled as an
estimate (linear, based on past betas).

### 8.6 Fan chart (W7)
A dedicated small SVG component (`FanChart`), **not** an overlay on recharts, so it doesn't depend on recharts internals.
Inputs: the recent closes the chart already loads and the analyst's scenario ranges (horizon, low/high percentiles per
scenario). It draws the history line, then the widening cone using its own scales. Opens with a clip-path reveal.

### 8.7 Wrapped / Year in review (W8)
- Backend: `GET /portfolio/review?year=YYYY`: return for the year, contributions, best and worst holding by return,
  biggest single day, number of trades, longest-held position, the value series by month. Built on the existing
  history and ledger services. **It reports gains from a full ledger replay across all accounts and is labelled as not a
  tax figure** (the tax report covers non-registered only).
- Frontend: a story player (progress bars, tap zones, hold-to-pause, swipe to close) and one component per slide, each
  with its own reveal timeline.
- Share card: drawn to a canvas, only after `document.fonts.ready` so it uses the real fonts; amounts hidden by default;
  shared with the iOS share sheet in the app (existing share/filesystem modules) or downloaded on the web.

### 8.8 Command palette (W11)
- `features/palette`: an index built locally from pages, actions, the user's holdings and watchlist and recent searches;
  fuzzy matching is a small pure function. Opens with Cmd/Ctrl-K (web, ignored while typing in a
  field), the `/` key outside fields, and a **visible button** (navigation bar on the phone).
- Market lookups use the existing search endpoint **only from an explicit "Search markets for ..." row**, debounced and
  length-limited, because search is rate-limited (20 new searches per minute per user).

### 8.9 Trade flight (W12)
`flip.js` measures the save button's rectangle and the target tab/nav icon's rectangle at the moment of saving, animates a
cloned token in a fixed-position layer with WAAPI, then triggers the icon pulse and the mood flare. If the target isn't
visible (keyboard open hides the tab bar, a very narrow layout) it falls back to a pulse at the bottom of the screen.

### 8.10 Milestones (W13)
Detected on the client from data already loaded: first trade, portfolio value thresholds (CA$10k, 25k, 50k, 100k...) and
all-time return thresholds. Seen milestones are stored locally. **All-time-high detection is deferred**: it needs the
full history on every dashboard load, which isn't worth the cost yet (listed as a possible server-side field later).

### 8.11 Transactions filters (F1 to F12)
Pure core, `features/filters/filterModel.js` (the part that matters most to test):
- `parseQuery(text, context)`: turns "aapl buy tfsa >500 2026" into typed tokens. Grammar rules are specified and tested:
  a word equal to a known action/account/asset-type/year/preset is a chip; `>n`, `<n`, `n-n` are amount ranges;
  `last Nd/m/y` and `YYYY` are date ranges; anything else is a **symbol/name contains** match; a token that is both a
  symbol and a keyword in the user's data (for example a ticker called `SOL` vs "sold") is resolved by exact symbol match
  first, and the chip shows what it was taken as so it can be changed.
- `applyFilters(trades, state)` with AND between groups and OR within a group.
- `facets(trades, state)`: counts per option *given the other groups' selections*; options with zero are flagged.
- `summarize(trades)`: counts, bought, sold, realised result (via the same average-cost logic the holdings use).
- `serialize / deserialize` for the address bar; `datePresets(today)` for presets.
- **Date rule:** all boundaries use the user's local calendar day, consistent with today's date inputs; "Tax year" presets
  use calendar years and say so.

UI and wiring:
- `useTransactions()` loads **one** `/transactions` request (no filter parameters), caches it in memory, and is
  invalidated by create/edit/delete/import. The server's filter parameters stay supported (additive) but unused by the new UI.
- `useFilterState()` mirrors the state to the URL with `replace` (no history spam). Typing is debounced.
- Components: `FilterBar` (TokenInput, ChipRow, FilterButton, SortMenu), `FilterPanel` (a `Popover` on desktop, a `Sheet`
  with detents on the phone, same content), `SummaryBar`, `ActivePills`, `EmptyResult`.
- Rendering: the list renders in **chunks of about 50** with an intersection sentinel instead of all rows at once;
  `useFlipList` animates only rows that are in the viewport and skips animation entirely when more than about 300 rows change.
- Offline: because the app caches the one request, filtering keeps working offline.

### 8.12 Shared-element navigation (W10)
Search result to detail, holding to its detail, trade row to edit sheet, X-Ray card to X-Ray page, all through the
view-transition helper (section 5.4). Search detail already uses `?asset=` in the address, so Back reverses it.

## 9. Phone architecture

- **Gating:** `isNative` (app), `(max-width: 768px)` and `(hover: none)` (mobile web), and capability checks
  (`startViewTransition`, `animation-timeline`). Effects declare which they need; the default is the plain behaviour.
- **iOS support matrix** (the app's minimum is iOS 17): 17 = reveal observer + CSS/WAAPI motion, no View Transitions and
  no scroll-linked animation (fallbacks used); 18 = adds View Transitions; 26 = adds scroll-driven animation. Every
  feature must pass on 17 with fallbacks.
- **Gesture registry** (`motion/gestures`): the page-level owners of touch (pull to refresh, sheet drag, the scrubber,
  terrain, story player, swipe actions) register what they own; `PullToRefresh`'s ignore list is generalised to read the
  registry (`data-gesture="own"`) instead of a hard-coded selector list. `useDrag` generalises `useSheetDrag`: pointer
  events, capture, axis lock, velocity, a clear cancel path.
- **Haptic map:** a table of beat to style (tick, soft, medium, thud, success) shared by all features, with throttling.
- **Light stretch on pull (P3):** `PullToRefresh` writes its pull distance to a CSS variable the light layer reads.
- **Performance on the phone:** time-based animations (60 or 120 Hz both fine); at most three `backdrop-filter` surfaces
  visible and never nested; canvas at DPR 2 with a watchdog; nothing animates behind the keyboard; effects pause when the
  app goes to the background (existing `app:background` event).
- **Existing modules to keep consistent:** `AppLock` (adds `app:unlocked`), `PageTransition` (disabled when View
  Transitions run), `NativeTitleBar` (fixed transition name), `offlineCache` (exclusions), `bootstrap` (starts
  `motionLevel`, applies theme before render).

## 10. Backend changes (all additive, small)

| Change | Used by | Notes |
|---|---|---|
| `GET /portfolio/history?detail=holdings` | W5, terrain scrub | top 40 holdings + rest per point; same rate limit as history |
| `GET /portfolio/review?year=` | W8 | new service; ledger replay across all accounts; cached per user and year |
| `GET /config` -> `{fx_level}` | remote effects kill switch | public, tiny, cached; lets effects be downgraded without an App Store release |

Nothing in the filters needs backend work. Old app versions are unaffected (all changes additive).

## 11. Performance budgets and measurement

Phase 0 records **baselines** (entry chunk gz size, per-route chunk sizes, landing LCP/CLS/TBT on a throttled mid-tier
profile, dashboard interaction latency). Budgets are then expressed against them:
- Entry chunk may grow by at most a small, stated amount (target: under 10 KB gz for tokens/motion infrastructure);
  new features load as lazy chunks (shader ≤ 8 KB, Terrain ≤ 25 KB, Wrapped ≤ 30 KB, palette ≤ 12 KB gz).
- Landing: LCP under 2.0 s on throttled 4G / mid-tier CPU; CLS under 0.05; no long task over 100 ms during the intro.
- Animations: 60 fps target on iPhone 12 class; the frame watchdog's thresholds are the runtime guard.
- Fonts: total font transfer on first load under about 90 KB gz (two critical files preloaded).

## 12. Testing architecture

| Layer | How |
|---|---|
| Pure logic (filter model, query parser, physics, mood mapping, motion-level decision, easing generator, FLIP maths, contrast) | Vitest (node), many cases including edge cases |
| Components and behaviour | Playwright in the repo (`frontend/e2e/`), against the local scratch backend (never production), per theme, viewport and motion level |
| Visual regression | Playwright screenshots of key screens x {Midnight, Black, Daylight} x {desktop, phone} x {full, reduced}; reviewed on change |
| Performance | Playwright trace of landing and dashboard (long tasks, CLS), compared with the baseline |
| Accessibility | reduced-motion run, keyboard-only run through filters/palette, contrast script, screen-reader labels checked on the DOM twins |
| Real device | TestFlight on at least one older and one newer iPhone before each phase is closed |

## 13. Rollout and safety

- **Phases** follow the plan's order; each phase is a series of small commits, ends green (lint, tests, build, e2e) and
  shippable. Phase 0 is invisible (tokens, fonts behind a flag, baselines).
- **Flags and kill switch:** a build-time `VITE_FX` default, a runtime override for testing (`localStorage fx=full|lite|off`),
  and a server-side `FX_LEVEL` setting served by a tiny public `GET /config` that the app and website read at startup
  (cached for a few minutes). Setting it to `lite` or `off` calms every device at once with no release. Because the app
  isn't launched yet, it ships in the very first App Store build, so there's never a version without it. Each heavy
  feature also checks its own flag and the motion level.
- **Rollback:** tokens and the palette are one-file changes; features are lazy chunks behind flags, so disabling one needs
  no code removal.
- **Website vs app:** website-only items (landing scene, scroll story) never ship in `dist-ios`; the build already
  separates the two outputs.
- **Privacy and policy:** no new data leaves the device (milestones, theme and effects settings are local); the
  privacy policy needs no change for the frontend work. Wrapped's endpoint reads only the user's own data.

## 14. New dependencies

Intended: **none for animation.** Dev dependencies: **Playwright** (`@playwright/test`, and its Chromium download) for browser
tests, and **stylelint** (with the standard config) for the "no raw colours" rule. Runtime: **Fontsource** font packages
(`@fontsource-variable/manrope`, `@fontsource-variable/fraunces`; self-hosted files). Anything else needs a written reason (size, maintenance,
alternatives).

## 15. Review: mistakes found in the design, and the fix for each

Found while analysing this architecture against the real code and the plan. Each fix is already written into the section
named, and the plan was updated where it was affected.

1. **No token system to build on (228 hard-coded hex values).** A palette/theme/area-tint change would silently miss
   places. *Fix:* token migration and a lint rule as a prerequisite (section 3.4, X0).
2. **CSS custom properties don't interpolate colours.** The glow would snap, not glide, when the mood changes.
   *Fix:* `@property` registration for hue and intensity, with an opacity-crossfade fallback (3.3).
3. **Two sources of truth for reduced motion** (the OS media query and a runtime watchdog) could disagree.
   *Fix:* a single `data-motion` level with defined precedence (5.1).
4. **View Transitions break with duplicate names, and would stack on the app's own page transition.**
   Naming every list row is invalid; double animation on the phone. *Fix:* name only the clicked row, fixed names for
   chrome, disable `PageTransition` when View Transitions run (5.4, 9).
5. **Time machine would have hit the server on every scrub frame** (the first version of W5 used a per-date endpoint),
   which breaks rate limits and feels laggy. *Fix:* one history request with `detail=holdings`, scrubbing entirely local
   (8.4); plan W5 updated.
6. **Mood would flash neutral on every load, and would leak performance in public.** *Fix:* persisted mood applied before
   first paint, decay when stale, privacy mode forces neutral (3.3).
7. **Serif numerals are not tabular** (measured: Fraunces and Instrument Serif both fail), which would make the odometer
   jitter. *Fix:* fixed-width digit cells for the odometer, with Manrope bold as the fallback for that one number; amounts
   everywhere else use Manrope's tabular figures (4).
8. **The intro could play over the Face ID lock or fight the splash.** *Fix:* explicit boot state machine and an
   `app:unlocked` event (8.1); plan W1 updated.
9. **Touch conflicts:** pull to refresh, sheet drag, the time-machine scrubber, terrain and swipe actions all want touches.
   *Fix:* a gesture registry and `useDrag`, with pull to refresh reading it (5/9).
10. **Canvas features are invisible to assistive tech, ignore the privacy blur and can drain battery.** *Fix:* a DOM twin
    for each, CSS blur on the canvas in privacy mode, simulation that sleeps when settled (7, 8.3).
11. **The command palette could burn the rate-limited market search on every keystroke.** *Fix:* local-first index and an
    explicit, debounced "Search markets" row (8.8).
12. **Filters on up to 20,000 trades:** loading everything client-side plus FLIP-animating thousands of rows would
    stutter, and the query grammar is ambiguous (a ticker that is also a word, date boundaries, time zones). *Fix:*
    progressive rendering in chunks, FLIP only for visible rows and only below a change threshold, a written grammar with
    exact-symbol-first resolution, and a single local-calendar-day rule (8.11).
13. **The landing page is client-rendered**, so a heavy scene could hurt LCP. *Fix:* the hero paints from CSS instantly,
    the shader is a lazy idle-time chunk with a cross-fade, budgets in section 11; build-time pre-rendering kept as an
    option (8.2).
14. **The plan claimed ProMotion (120 Hz) support; the web view's frame rate isn't guaranteed.** *Fix:* animations are
    time-based so any rate looks right; the plan's P7 line was reworded to "designed for 60 fps; time-based so 120 Hz
    also works" (5, 7, 9).
15. **All-time-high milestone needs the full history on each load.** *Fix:* deferred; v1 uses thresholds only (8.10).
16. **Share card fonts and privacy:** a canvas image drawn before fonts load looks wrong, and a shared image could leak
    amounts. *Fix:* wait for `document.fonts.ready`; amounts hidden by default (8.7).
17. **Trade-flight target may not exist** (keyboard open hides the tab bar). *Fix:* measured at save time with a
    fallback pulse (8.9).
18. **Vitest is node-only, so DOM behaviour can't be unit-tested.** *Fix:* all logic lives in pure modules; DOM behaviour
    is covered by Playwright in the repo (12).
19. **Wrapped's "gains" would disagree with the tax report** (which covers non-registered accounts only).
    *Fix:* separate ledger-replay computation labelled "not a tax figure" (8.7).
20. **Large new responses could overflow the app's offline cache.** *Fix:* the holdings-detail history is excluded from
    the persisted cache (8.4, 9); the size limits of `offlineCache` are verified before enabling.
21. **Too much glass:** several stacked `backdrop-filter` layers are costly on phones. *Fix:* at most three surfaces and
    never nested (C7 in the plan, 9 here).
22. **Release risk for the app:** a heavy effect bug would need an App Store release to fix. *Fix:* optional remote
    `fx_level` config plus per-feature `motionLevel` guards and flags (10, 13).

## 16. Open questions

Settled since the first draft: Daylight in, kill switch in (from the first release), saved views dropped, Playwright in.
Fonts are chosen (Manrope + Fraunces). Still open: the loss-colour tweak (plan D1) and the one small backend change for
the time machine (plan D2).
