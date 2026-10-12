import {changeClass, formatMoney, formatPercent, formatSignedMoney} from "../utils/format.js";

const RANGE_LABELS = {
    day: "Today's return",
    week: "Past week",
    month: "Past month",
    year: "Past year",
    all: "All-time return",
};

function DashboardStats({stats, loading, currency, range}) {
    const change = stats.curr_timeperiod;
    const startValue = stats.value - change;
    const changePct = startValue > 0 ? (change / startValue) * 100 : null;

    return (
        <div className="dashboard-stats">
            <div className="stat-card">
                <div className="stat-label">Portfolio value</div>
                {loading ? (
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
