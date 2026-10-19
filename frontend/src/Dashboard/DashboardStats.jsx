import {changeClass, formatMoney, formatPercent, formatSignedMoney} from "../utils/format.js";

const RANGE_LABELS = {
    day: "Today's return",
    week: "Past week",
    month: "Past month",
    year: "Past year",
    all: "All-time return",
};

// `loading`: the selected range's return is still loading. `valueLoading`: nothing has loaded yet; the portfolio
// value doesn't depend on the range, so it stays on screen while another range loads.
function DashboardStats({stats, loading, valueLoading = loading, currency, range}) {
    const change = stats.curr_timeperiod;
    // the backend's base: value at the start of the period + money put in (all time: cost of every buy).
    // value − change was wrong once anything had been sold (e.g. +1300% for a +13% gain)
    const basis = Number(stats.basis);
    const changePct = basis > 0 ? (change / basis) * 100 : null;

    return (
        <div className="dashboard-stats">
            <div className="stat-card">
                <div className="stat-label">Portfolio value</div>
                {valueLoading ? (
                    <span className="skeleton stat-skeleton"/>
                ) : (
                    <div className="stat-value">{formatMoney(stats.value, currency)}</div>
                )}
            </div>

            <div className="stat-card">
                <div className="stat-label">{RANGE_LABELS[range] ?? "Period return"}</div>
                {loading ? (
                    <span className="skeleton stat-skeleton"/>
                ) : (
                    <div className={`stat-value ${changeClass(change)}`}>
                        {formatSignedMoney(change, currency)}
                        {changePct !== null && (
                            <span className="stat-pct">{formatPercent(changePct)}</span>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

export default DashboardStats;
