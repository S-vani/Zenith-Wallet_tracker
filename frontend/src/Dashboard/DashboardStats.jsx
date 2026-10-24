import {changeClass, formatMoney, formatPercent, formatSignedMoney} from "../utils/format.js";
import {unpricedNote} from "./dashboardText.js";

const RANGE_LABELS = {
    day: "Today's return",
    week: "Past week",
    month: "Past month",
    year: "Past year",
    all: "All-time return",
};

// `loading`: the selected range's return is still loading. `valueLoading`: nothing has loaded yet; the portfolio
// value doesn't depend on the range, so it stays on screen while another range loads. `unavailable`: nothing could
// be loaded, so both cards show "—" (the page shows the error and a Try again button) instead of shimmering forever.
// The amount as one unbreakable piece: on the website it shrinks with its card by its length (--chars, see
// Dashboard.css) instead of wrapping between digits. The app shrinks it with fitNumbers.js instead
function Amount({text}) {
    return (
        <span className="stat-amount" style={{"--chars": text.length}}
              title={text.length > 16 ? text : undefined}>{text}</span>
    );
}

function DashboardStats({stats, loading, valueLoading = loading, unavailable = false, currency, range}) {
    const change = stats.curr_timeperiod;
    // the backend's base: value at the start of the period + money put in (all time: cost of every buy).
    // value − change was wrong once anything had been sold (e.g. +1300% for a +13% gain)
    const basis = Number(stats.basis);
    const changePct = basis > 0 ? (change / basis) * 100 : null;
    // holdings with no price anywhere are left out of both numbers; the list is about now, so it's the same for
    // every range and can stay while another range loads
    const missing = valueLoading || unavailable ? null : unpricedNote(stats.unpriced);

    return (
        <>
            <div className="dashboard-stats">
                <div className="stat-card">
                    <div className="stat-label">Portfolio value</div>
                    {unavailable ? (
                        <div className="stat-value">—</div>
                    ) : valueLoading ? (
                        <span className="skeleton stat-skeleton"/>
                    ) : (
                        <div className="stat-value"><Amount text={formatMoney(stats.value, currency)}/></div>
                    )}
                </div>

                <div className="stat-card">
                    <div className="stat-label">{RANGE_LABELS[range] ?? "Period return"}</div>
                    {unavailable ? (
                        <div className="stat-value">—</div>
                    ) : loading ? (
                        <span className="skeleton stat-skeleton"/>
                    ) : (
                        <div className={`stat-value ${changeClass(change)}`}>
                            <Amount text={formatSignedMoney(change, currency)}/>
                            {changePct !== null && (
                                <span className="stat-pct">{formatPercent(changePct)}</span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {missing && <p className="unpriced-note">{missing}</p>}
        </>
    );
}

export default DashboardStats;
