import {useEffect, useState} from "react";
import {getPortfolioHistory} from "../services/api.js";
import useRefreshKey from "../native/useRefreshKey.js";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {formatMoney} from "../utils/format.js";
import {CHART_DOWN, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, dailyTicks, tooltipDate} from "../utils/chart.js";

const RANGE_DAYS = {
    day: 1,
    week: 7,
    month: 30,
    year: 365,
};

function DashboardChart({range, currency, dateJoined, trendUp}) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [now] = useState(() => Date.now());

    // "All" goes back to the day the user joined (a year if that's unknown)
    let days = RANGE_DAYS[range] ?? 1;
    if (range === "all") {
        const joined = dateJoined ? new Date(dateJoined).getTime() : NaN;
        days = Number.isFinite(joined) ? Math.max(1, Math.ceil((now - joined) / (1000 * 60 * 60 * 24))) : 365;
    }

    const refreshKey = useRefreshKey();

    useEffect(() => {
        let ignore = false;

        const loadDashboardChart = async () => {
            try {
                setLoading(true);
                setError(null);
                const res = await getPortfolioHistory(days);
                if (!ignore) setData(res);
            } catch (err) {
                if (!ignore) setError(err.message);
            } finally {
                if (!ignore) setLoading(false);
            }
        };

        loadDashboardChart();
        return () => {
            ignore = true;
        };
    }, [days, refreshKey]);

    const formatTick = (v) => {
        const date = new Date(v);
        if (days === 1) {
            return date.toLocaleTimeString(undefined, {hour: "numeric", minute: "2-digit"});
        }
        if (days > 365) {
            return date.toLocaleDateString(undefined, {month: "short", year: "2-digit"});
        }
        return date.toLocaleDateString(undefined, {month: "short", day: "numeric"});
    };

    const hasValues = data.some((d) => d.value > 0);
    // value charts start at 0 before the first buy, so use the period's return (from the card) for the colour
    const isUp = trendUp ?? (data.length > 1 && data[data.length - 1].value >= data[0].value);
    const color = isUp ? CHART_UP : CHART_DOWN;

    let body;
    if (loading) {
        body = (
            <div className="state-message">
                <div className="spinner"/>
                Building your portfolio history…
            </div>
        );
    } else if (error) {
        body = <div className="state-message"><p className="alert-error">{error}</p></div>;
    } else if (!hasValues) {
        body = (
            <div className="state-message">
                <strong>No history yet</strong>
                Add a transaction and your portfolio value will be charted here.
            </div>
        );
    } else {
        body = (
            <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_DIMENSION}>
                <AreaChart data={data} margin={{top: 8, right: 8, left: 0, bottom: 0}}>
                    <defs>
                        <linearGradient id="dashboardFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={color} stopOpacity={0.3}/>
                            <stop offset="100%" stopColor={color} stopOpacity={0}/>
                        </linearGradient>
                    </defs>
                    <XAxis
                        dataKey="time"
                        ticks={days === 7 ? dailyTicks(data) : undefined}
                        minTickGap={40}
                        tickMargin={10}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        axisLine={{stroke: "rgba(255,255,255,0.06)"}}
                        tickLine={false}
                        tickFormatter={formatTick}
                    />
                    <YAxis
                        width={70}
                        domain={["auto", "auto"]}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v) => formatMoney(v, currency, {notation: "compact", minimumFractionDigits: 0})}
                    />
                    <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        separator=": "
                        formatter={(value) => [formatMoney(value, currency), "Value"]}
                        labelFormatter={(value) => tooltipDate(value, days <= 7)}
                        cursor={{stroke: "rgba(59,130,246,0.3)", strokeWidth: 1}}
                    />
                    <Area
                        type="monotone"
                        dataKey="value"
                        stroke={color}
                        strokeWidth={2}
                        fill="url(#dashboardFill)"
                        dot={false}
                        activeDot={{r: 4, fill: color, strokeWidth: 0}}
                    />
                </AreaChart>
            </ResponsiveContainer>
        );
    }

    return (
        <div className="chart-wrapper-dashboard">
            <div className="chart-body">{body}</div>
        </div>
    );
}

export default DashboardChart;
