import {useEffect, useRef, useState} from "react";
import {Pie, PieChart, ResponsiveContainer, Tooltip} from "recharts";
import {getPortfolioAllocation} from "../services/api.js";
import {formatMoney} from "../utils/format.js";
import {INITIAL_DIMENSION, TOOLTIP_STYLE} from "../utils/chart.js";
import useRefreshKey from "../native/useRefreshKey.js";
import {dashboardKey, readDashboardCache, writeDashboardCache} from "./dashboardCache.js";
import {unpricedNote} from "./dashboardText.js";
import {allocationRows, allocationSummary, availableViews, formatWeight} from "./allocationData.js";

import "../css/Allocation.css";

// only called from event handlers and state initialisers, never while rendering
const currentTime = () => Date.now();

// What each tab's breakdown means where it isn't obvious
const VIEW_NOTES = {
    account: "Each trade counts in the account it was logged in. A sell comes out of its own account first; if that " +
        "account holds too little of it, the rest comes out of “Not set”, then your largest account.",
    currency: "Stocks are grouped by the currency they trade in. Crypto has no listing currency, so it's its own group.",
};

// The dashboard's "X-ray": today's value split by asset type, account, holding or listing currency.
// `currency` is the user's (null until /user loads, so nothing is fetched or cached under a guess); `unavailable`
// means the account itself couldn't be loaded, and the page already shows that error with its Try again button.
function AllocationCard({currency, unavailable = false}) {
    const [view, setView] = useState("asset_type");
    const [loaded, setLoaded] = useState({}); // cache key -> reply, for this visit
    const [error, setError] = useState(null);
    const [attempt, setAttempt] = useState(0); // bumped by "Try again"
    const [clock, setClock] = useState(currentTime); // "now" for the shared cache's age check
    const fetchedWith = useRef({}); // key -> refreshKey of the last fetch made while the card is open
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    // the dashboard's one-minute cache (keyed by session token + currency), so coming back to the dashboard is
    // instant; "allocation" never clashes with its range keys
    const key = currency ? dashboardKey("allocation", 0, currency) : null;
    const data = key ? loaded[key] ?? readDashboardCache(key, clock) : undefined;

    useEffect(() => {
        if (!key) return; // waiting for the user's currency
        const fresh = readDashboardCache(key) !== undefined;
        if (fresh && fetchedWith.current[key] === refreshKey) return;

        let ignore = false;
        fetchedWith.current[key] = refreshKey;

        getPortfolioAllocation()
            .then((reply) => {
                writeDashboardCache(key, reply);
                setLoaded((all) => ({...all, [key]: reply}));
                if (!ignore) setError(null);
            })
            .catch((err) => {
                delete fetchedWith.current[key]; // try again next time
                if (!ignore) setError(err.message);
            });

        return () => {
            ignore = true;
        };
    }, [key, refreshKey, attempt]);

    const retry = () => {
        setError(null); // back to the spinner while it tries again
        setClock(currentTime());
        setAttempt((n) => n + 1);
    };

    const views = availableViews(data);
    const activeView = views.some((v) => v.value === view) ? view : views[0]?.value ?? "asset_type";
    const rows = data ? allocationRows(data, activeView) : [];
    const total = Number(data?.total) || 0;
    const missing = data ? unpricedNote(data.unpriced) : null;

    let body;
    if (!data && error) {
        body = (
            <div className="alert-error alert-retry" role="alert">
                <span>{error}</span>
                <button type="button" className="btn" onClick={retry}>Try again</button>
            </div>
        );
    } else if (!data && unavailable) {
        // not role="alert": the page announces the error once, next to its Try again button
        body = <div className="state-message"><p className="alert-error">Your allocation couldn't be loaded.</p></div>;
    } else if (!data) {
        body = (
            <div className="state-message allocation-state">
                <div className="spinner"/>
                Working out your allocation…
            </div>
        );
    } else if (total <= 0) {
        body = (
            <div className="state-message allocation-state">
                {missing ? (
                    <>
                        <strong>Nothing to split up right now</strong>
                        {missing}
                    </>
                ) : (
                    <>
                        <strong>No holdings yet</strong>
                        Once you add a trade, you'll see how your portfolio is spread across assets and accounts.
                    </>
                )}
            </div>
        );
    } else {
        body = (
            <>
                {error && (
                    <div className="alert-error alert-retry" role="alert">
                        <span>{error}</span>
                        <button type="button" className="btn" onClick={retry}>Try again</button>
                    </div>
                )}

                <div className="segmented allocation-tabs" role="group" aria-label="Show allocation by">
                    {views.map(({value, label}) => (
                        <button
                            key={value}
                            type="button"
                            className={activeView === value ? "active" : ""}
                            aria-pressed={activeView === value}
                            onClick={() => setView(value)}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                <figure className="allocation-figure">
                    {/* the donut is a picture to a screen reader, so it gets the numbers as text */}
                    <p className="visually-hidden">{allocationSummary(rows, activeView, currency)}</p>
                    <div className="allocation-body">
                        <div className="allocation-donut" aria-hidden="true">
                            <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_DIMENSION}>
                                {/* no keyboard layer: the legend next to it has every number as text */}
                                <PieChart accessibilityLayer={false}>
                                    <Pie
                                        // recharts colours a slice from its entry's `fill` (not `color`)
                                        data={rows.map((r) => ({...r, fill: r.color}))}
                                        dataKey="value"
                                        nameKey="label"
                                        innerRadius="62%"
                                        outerRadius="100%"
                                        startAngle={90}
                                        endAngle={-270}
                                        stroke="#161b28"
                                        strokeWidth={2}
                                        isAnimationActive={false}
                                    />
                                    <Tooltip
                                        contentStyle={TOOLTIP_STYLE}
                                        itemStyle={{color: "#f5f7ff"}}
                                        separator=": "
                                        formatter={(value, name, item) => [
                                            `${formatMoney(value, currency)} (${formatWeight(item?.payload?.weight)})`,
                                            name,
                                        ]}
                                    />
                                </PieChart>
                            </ResponsiveContainer>
                        </div>

                        <ul className="allocation-legend" aria-hidden="true">
                            {rows.map((r) => (
                                <li key={r.key}>
                                    <span className="allocation-swatch" style={{background: r.color}}/>
                                    <span className="allocation-label">{r.label}</span>
                                    <span className="allocation-value">{formatMoney(r.value, currency)}</span>
                                    <span className="allocation-pct">{formatWeight(r.weight)}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                    {VIEW_NOTES[activeView] && (
                        <figcaption className="chart-note">{VIEW_NOTES[activeView]}</figcaption>
                    )}
                </figure>

                {missing && <p className="unpriced-note">{missing}</p>}
            </>
        );
    }

    return (
        <section className="allocation-card" aria-labelledby="allocation-title">
            <header className="allocation-header">
                <h2 id="allocation-title" className="allocation-title">Allocation</h2>
                {data && total > 0 && (
                    <span className="allocation-total">Total {formatMoney(total, currency)}</span>
                )}
            </header>
            {body}
        </section>
    );
}

export default AllocationCard;
