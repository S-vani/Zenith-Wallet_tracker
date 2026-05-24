function DashboardStats({stats}) {

    let statName = "stat-value"
    if (stats.curr_timeperiod > 0) {
        statName += " positive"
    } else {
        statName += " negative"
    }


    return (
        <div className="dashboard-stats">
            <div className="stat-card">
                <div className="stat-label">Portfolio Value</div>
                <div className="stat-value">$ {stats.value.toFixed(2)}</div>
            </div>

            <div className="stat-card">
                <div className="stat-label">Period Return</div>
                <div className={statName}>$ {stats.curr_timeperiod.toFixed(2)}</div>

            </div>
        </div>
    );
}

export default DashboardStats;
