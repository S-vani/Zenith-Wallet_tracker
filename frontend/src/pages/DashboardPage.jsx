import {useEffect, useState} from "react";
import {getDashboardStats, getUser} from "../services/api.js";
import DashboardStats from "../Dashboard/DashboardStats.jsx";
import {useNavigate} from "react-router-dom";
import DashboardChart from "../Dashboard/DashboardChart.jsx";

import "../css/Dashboard.css";

const TIME_RANGES = [
    {label: "1D", value: "day"},
    {label: "1W", value: "week"},
    {label: "1M", value: "month"},
    {label: "1Y", value: "year"},
    {label: "All", value: "all"},
];

function DashboardPage() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [user, setUser] = useState({});
    const [activeRange, setActiveRange] = useState("day");
    const [stats, setStats] = useState({value: 0.0, curr_timeperiod: 0.0});
    const navigate = useNavigate();

    const loadDashboard = async (time_span) => {
        try {
            setLoading(true);
            setError(null);
            const data = await getDashboardStats(time_span);
            setStats(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const loadUser = async () => {
        const userInfo = await getUser();
        setUser(userInfo);
    };

    useEffect(() => {
        loadUser();
        loadDashboard("day");
    }, []);

    const handleRangeClick = (value) => {
        setActiveRange(value);
        loadDashboard(value);
    };

    const greeting = () => {
        const h = new Date().getHours();
        if (h < 12) return "Good morning";
        if (h < 17) return "Good afternoon";
        return "Good evening";
    };

    return (
        <div className="dashboard-page">
            <h1 className="page-headers" id="dashboard-header">
                {greeting()}, {user.name}
            </h1>

            {error && <p className="error">{error}</p>}

            <DashboardStats stats={stats}/>

            <div className="dashboard-controls">
                {TIME_RANGES.map(({label, value}) => (
                    <button
                        key={label}
                        className={`chart-range-btn${activeRange === (value ?? "all") ? " active" : ""}`}
                        onClick={() => handleRangeClick(value)}
                    >
                        {label}
                    </button>
                ))}

                <button
                    className="dashboard-nav-btn"
                    onClick={() => navigate("/Holdings")}
                >
                    Holdings →
                </button>
            </div>

            {loading ? (
                <p className="loading-dashboard">Fetching Portfolio History...</p>
            ) : (
                <DashboardChart range={activeRange}/>
            )}
        </div>
    );
}

export default DashboardPage;
