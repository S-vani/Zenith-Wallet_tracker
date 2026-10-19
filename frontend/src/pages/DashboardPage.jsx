import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {getDashboardStats, getPortfolioHistory} from "../services/api.js";
import DashboardStats from "../Dashboard/DashboardStats.jsx";
import DashboardChart from "../Dashboard/DashboardChart.jsx";
import {dashboardKey, readDashboardCache, writeDashboardCache} from "../Dashboard/dashboardCache.js";
import {useUser} from "../context/UserContext.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";

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

// Days of history to chart; "All" goes back to the day the user joined (a year if that's unknown)
function rangeDays(range, dateJoined, now) {
    const fixed = TIME_RANGES.find((r) => r.value === range)?.days;
    if (fixed) return fixed;
    const joined = dateJoined ? new Date(dateJoined).getTime() : NaN;
    return Number.isFinite(joined) ? Math.max(1, Math.ceil((now - joined) / DAY_MS)) : 365;
}

const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
};

function DashboardPage() {
    usePageTitle("Dashboard");

    const {user, currency} = useUser();
    const [error, setError] = useState(null);
    const [activeRange, setActiveRange] = useState("day");
    const [clock, setClock] = useState(currentTime); // "now" for cache ages, moved on by range clicks
    // everything loaded while the page is open, by cache key: {range, days, stats, chart}
    const [loaded, setLoaded] = useState({});
    const [shownKey, setShownKey] = useState(null); // the newest fully loaded range, shown while another loads
    const fetchedWith = useRef({}); // key -> refreshKey of the last fetch made while this page is open
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    const days = rangeDays(activeRange, user?.date_joined, clock);
    const key = dashboardKey(activeRange, days, currency);

    // Stats and chart always come from the same range and are swapped together, so the chart's colour and the
    // return next to it can never disagree
    const current = loaded[key] ?? readDashboardCache(key, clock);
    const shown = current ?? loaded[shownKey] ?? null;
    const pending = !current; // the selected range is still loading; an older one stays on screen, dimmed

    useEffect(() => {
        // fetched during this visit and nothing asked for a refresh since: the saved copy is good for a minute
        const fresh = readDashboardCache(key) !== undefined;
        if (fresh && fetchedWith.current[key] === refreshKey) return;

        let ignore = false; // the user may already have clicked another range
        fetchedWith.current[key] = refreshKey;

        Promise.all([getDashboardStats(activeRange), getPortfolioHistory(days)])
            .then(([stats, chart]) => {
                const entry = {range: activeRange, days, stats, chart};
                writeDashboardCache(key, entry);
                setLoaded((all) => ({...all, [key]: entry}));
                // even a range the user already left is a better placeholder than nothing while the next one loads
                setShownKey(key);
                if (!ignore) setError(null);
            })
            .catch((err) => {
                delete fetchedWith.current[key]; // try again next time
                if (!ignore) setError(err.message);
            });

        return () => {
            ignore = true;
        };
    }, [key, activeRange, days, refreshKey]);

    const selectRange = (value) => {
        setClock(currentTime());
        setActiveRange(value);
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

            {error && shown && <p className="alert-error" role="alert">{error}</p>}

            {/* the portfolio value is the same for every range, so it stays on screen while a range loads */}
            <DashboardStats stats={stats} loading={pending} valueLoading={!shown} currency={currency}
                            range={activeRange}/>

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

            <DashboardChart entry={shown} updating={pending && !!shown} currency={currency}
                            error={shown ? null : error}/>
        </div>
    );
}

export default DashboardPage;
