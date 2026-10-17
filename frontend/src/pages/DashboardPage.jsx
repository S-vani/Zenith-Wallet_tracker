import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getDashboardStats} from "../services/api.js";
import DashboardStats from "../Dashboard/DashboardStats.jsx";
import DashboardChart from "../Dashboard/DashboardChart.jsx";
import {useUser} from "../context/UserContext.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";

import "../css/Dashboard.css";

const TIME_RANGES = [
    {label: "1D", value: "day"},
    {label: "1W", value: "week"},
    {label: "1M", value: "month"},
    {label: "1Y", value: "year"},
    {label: "All", value: "all"},
];

const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
};

function DashboardPage() {
    usePageTitle("Dashboard");

    const {user, currency} = useUser();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [activeRange, setActiveRange] = useState("day");
    const [stats, setStats] = useState({value: 0.0, curr_timeperiod: 0.0});
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    useEffect(() => {
        let ignore = false; // ignore responses for a range the user already clicked away from

        const loadDashboard = async () => {
            try {
                setLoading(true);
                setError(null);
                const data = await getDashboardStats(activeRange);
                if (!ignore) setStats(data);
            } catch (err) {
                if (!ignore) setError(err.message);
            } finally {
                if (!ignore) setLoading(false);
            }
        };

        loadDashboard();
        return () => {
            ignore = true;
        };
    }, [activeRange, refreshKey]);

    const firstName = user?.name?.split(" ")[0];

    return (
        <div className="app-page dashboard-page">
            <header>
                <h1 className="page-headers">
                    {greeting()}{firstName ? `, ${firstName}` : ""}
                </h1>
                <p className="page-subtitle">Here's how your portfolio is doing.</p>
            </header>

            {error && <p className="alert-error" role="alert">{error}</p>}

            <DashboardStats stats={stats} loading={loading} currency={currency} range={activeRange}/>

            <div className="dashboard-controls">
                <div className="segmented" role="group" aria-label="Time range">
                    {TIME_RANGES.map(({label, value}) => (
                        <button
                            key={label}
                            className={activeRange === value ? "active" : ""}
                            aria-pressed={activeRange === value}
                            onClick={() => setActiveRange(value)}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                <Link className="btn btn-primary dashboard-nav-btn" to="/holdings">
                    Holdings →
                </Link>
            </div>

            <DashboardChart range={activeRange} currency={currency} dateJoined={user?.date_joined}
                            trendUp={loading || error ? undefined : stats.curr_timeperiod >= 0}/>
        </div>
    );
}

export default DashboardPage;
