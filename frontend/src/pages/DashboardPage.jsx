import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {getDashboardStats, getPortfolioAllocation, getPortfolioHistory} from "../services/api.js";
import DashboardStats from "../Dashboard/DashboardStats.jsx";
import DashboardChart from "../Dashboard/DashboardChart.jsx";
import AllocationCard from "../Dashboard/AllocationCard.jsx";
import {dashboardKey, readDashboardCache, writeDashboardCache} from "../Dashboard/dashboardCache.js";
import {useUser} from "../context/UserContext.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";
import {rememberPortfolioForSiri} from "../native/screens.js";

import "../css/Dashboard.css";

const TIME_RANGES = [
    {label: "1D", value: "day", days: 1},
    {label: "1W", value: "week", days: 7},
    {label: "1M", value: "month", days: 30},
    {label: "1Y", value: "year", days: 365},
    {label: "All", value: "all"},
];

const DAY_MS = 1000 * 60 * 60 * 24;

// only called from event handlers and state initialisers, never while rendering
const currentTime = () => Date.now();

// Days of history to chart. "All" asks the server for "all": it starts the chart at the first trade, which this page
// doesn't know (going by date_joined squashed backdated or imported history into a single day)
function rangeDays(range) {
    return TIME_RANGES.find((r) => r.value === range)?.days ?? "all";
}

// How many days a loaded chart covers, so "All" gets the same tooltips (times or dates) as a fixed range that long
function chartDays(days, chart) {
    if (days !== "all") return days;
    const first = Date.parse(chart?.[0]?.time);
    const last = Date.parse(chart?.[chart.length - 1]?.time);
    return Number.isFinite(first) && Number.isFinite(last) ? Math.max(1, Math.round((last - first) / DAY_MS)) : 365;
}

const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
};

function DashboardPage() {
    usePageTitle("Dashboard");

    const {user, currency, error: userError, reload: reloadUser} = useUser();
    // {key, message}: the error belongs to the range (and currency) that failed, so it goes away when another one,
    // already loaded, is picked
    const [failure, setFailure] = useState(null);
    const [attempt, setAttempt] = useState(0); // bumped by "Try again" to fetch the selected range again
    const [activeRange, setActiveRange] = useState("day");
    const [clock, setClock] = useState(currentTime); // "now" for cache ages, moved on by range clicks
    // everything loaded while the page is open, by cache key: {range, days, stats, chart, allocation}
    const [loaded, setLoaded] = useState({});
    const [shownKey, setShownKey] = useState(null); // the newest fully loaded range, shown while another loads
    const fetchedWith = useRef({}); // key -> refreshKey of the last fetch made while this page is open
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    const days = rangeDays(activeRange);
    // no key until the user (and so the currency every amount comes in) is known, so nothing is cached or shown
    // under a guessed currency
    const key = currency ? dashboardKey(activeRange, days, currency) : null;

    // Stats, chart and allocation always come from the same load and are swapped together, so the chart's colour
    // and the return next to it can never disagree, and neither can the value card and the allocation total
    const current = key ? loaded[key] ?? readDashboardCache(key, clock) : undefined;
    // another range stays on screen meanwhile, but only one loaded in this currency: amounts in the old currency
    // would otherwise show under the new one's symbol (the currency can change in another tab)
    const previous = key ? loaded[shownKey] : undefined;
    const shown = current ?? (previous?.currency === currency ? previous : null);
    const pending = !current; // the selected range is still loading; an older one stays on screen, dimmed
    const error = failure?.key === key ? failure.message : null;
    // nothing to show and the load failed (or the account couldn't be loaded): "—" and the error, not skeletons
    const loadError = error ?? (currency ? null : userError);
    const failed = !shown && Boolean(loadError);

    useEffect(() => {
        if (!key) return; // waiting for the user's currency
        // fetched during this visit and nothing asked for a refresh since: the saved copy is good for a minute
        const fresh = readDashboardCache(key) !== undefined;
        if (fresh && fetchedWith.current[key] === refreshKey) return;

        let ignore = false; // the user may already have clicked another range
        fetchedWith.current[key] = refreshKey;

        // a failed allocation only fails its own card (with its own Try again), not the whole dashboard
        const allocation = getPortfolioAllocation()
            .then((reply) => ({allocation: reply}), (err) => ({allocationError: err.message}));
        Promise.all([getDashboardStats(activeRange), getPortfolioHistory(days), allocation])
            .then(([stats, chart, split]) => {
                const entry = {range: activeRange, days: chartDays(days, chart), stats, chart, currency, ...split};
                writeDashboardCache(key, entry);
                setLoaded((all) => ({...all, [key]: entry}));
                // even a range the user already left is a better placeholder than nothing while the next one loads
                setShownKey(key);
                setFailure((f) => (f?.key === key ? null : f));
                // app only: what Siri reads out for "What's my portfolio worth" (value + today's change)
                if (activeRange === "day") rememberPortfolioForSiri(stats, currency);
            })
            .catch((err) => {
                delete fetchedWith.current[key]; // try again next time
                if (!ignore) setFailure({key, message: err.message});
            });

        return () => {
            ignore = true;
        };
    }, [key, activeRange, days, refreshKey, attempt, currency]);

    const selectRange = (value) => {
        setClock(currentTime());
        setActiveRange(value);
    };

    const retry = () => {
        setFailure(null); // back to the loading skeletons while it tries again
        if (!currency) reloadUser();
        setAttempt((n) => n + 1);
    };

    // the allocation failed but the rest loaded: load the range again (its saved copy would otherwise be reused)
    const retryAllocation = () => {
        if (key) delete fetchedWith.current[key];
        setClock(currentTime());
        setAttempt((n) => n + 1);
    };

    const firstName = user?.name?.split(" ")[0];
    const stats = current?.stats ?? shown?.stats ?? {value: 0, curr_timeperiod: 0};

    return (
        <div className="app-page dashboard-page">
            <header>
                <h1 className="page-headers">
                    {greeting()}{firstName ? `, ${firstName}` : ""}
                </h1>
                <p className="page-subtitle">Here's how your portfolio is doing.</p>
            </header>

            {loadError && (
                <div className="alert-error alert-retry" role="alert">
                    <span>{loadError}</span>
                    <button type="button" className="btn" onClick={retry}>Try again</button>
                </div>
            )}

            {/* the portfolio value is the same for every range, so it stays on screen while a range loads */}
            <DashboardStats stats={stats} loading={pending && !failed} valueLoading={!shown && !failed}
                            unavailable={failed} currency={currency} range={activeRange}/>

            <div className="dashboard-controls">
                <div className="segmented" role="group" aria-label="Time range">
                    {TIME_RANGES.map(({label, value}) => (
                        <button
                            key={label}
                            className={activeRange === value ? "active" : ""}
                            aria-pressed={activeRange === value}
                            onClick={() => selectRange(value)}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                <Link className="btn btn-primary dashboard-nav-btn" to="/holdings">
                    Holdings →
                </Link>
            </div>

            {/* the error and its Try again button are above, so the chart only says it couldn't load */}
            <DashboardChart entry={shown} updating={pending && !!shown} currency={currency}
                            error={failed ? "Your portfolio history couldn't be loaded." : null}/>

            {/* the same for every range, but loaded with each one so its total matches the value card above;
                a dashboard error is already shown above */}
            <AllocationCard currency={currency} data={shown?.allocation} error={shown?.allocationError ?? null}
                            onRetry={retryAllocation} unavailable={failed}/>
        </div>
    );
}

export default DashboardPage;
