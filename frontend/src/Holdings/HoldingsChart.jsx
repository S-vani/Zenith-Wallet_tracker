import {useEffect, useState} from "react";
import {getPriceHistory} from "../services/api.js";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {useUser} from "../context/UserContext.jsx";
import {formatMoney} from "../utils/format.js";
import {CHART_DOWN, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, dailyTicks, tooltipDate} from "../utils/chart.js";

const RANGES = ["1D", "1W", "1M", "1Y", "5Y"];

function HoldingChart({symbol, type, initialRange = "1M", compact = false}) {
    const {currency} = useUser();
    const [range, setRange] = useState(initialRange);
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let ignore = false;

        const load = async () => {
            try {
                setLoading(true);
                setError(null);
                const res = await getPriceHistory(symbol, type, range);
                if (!ignore) setData(res.data.map(p => ({time: p.time, price: p.price})));
            } catch (err) {
                if (!ignore) setError(err.message);
            } finally {
                if (!ignore) setLoading(false);
            }
        };

        load();
        return () => {
            ignore = true;
        };
    }, [symbol, range, type]);

    const isUp = data.length > 1 && data[data.length - 1].price >= data[0].price;
    const color = isUp ? CHART_UP : CHART_DOWN;
    const gradientId = `holdingFill-${type}-${symbol}`;
    const intraday = range === "1D" || range === "1W";

    const formatTick = (v) => {
        const date = new Date(v);
        if (range === "1D") return date.toLocaleTimeString(undefined, {hour: "numeric", minute: "2-digit"});
        if (range === "5Y") return date.toLocaleDateString(undefined, {month: "short", year: "numeric"});
        return date.toLocaleDateString(undefined, {month: "short", day: "numeric"});
    };

    // big prices (e.g. BTC) get compact axis labels so they don't eat the chart width
    const maxPrice = Math.max(0, ...data.map((d) => d.price));
    const formatPriceTick = (value) => formatMoney(value, currency, maxPrice >= 10000
        ? {notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 1}
        : {maximumFractionDigits: maxPrice < 1 ? 4 : 2});

    let body;
    if (loading) {
        body = <div className="state-message"><div className="spinner"/></div>;
    } else if (error) {
        body = <div className="state-message"><p className="alert-error">{error}</p></div>;
    } else if (data.length === 0) {
        body = <div className="state-message">No price data available for this range.</div>;
    } else {
        body = (
            <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_DIMENSION}>
                <AreaChart data={data} margin={{top: 10, right: 10, left: 0, bottom: 0}}>
                    <defs>
                        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={color} stopOpacity={0.25}/>
                            <stop offset="100%" stopColor={color} stopOpacity={0}/>
                        </linearGradient>
                    </defs>
                    <XAxis
                        dataKey="time"
                        ticks={range === "1W" ? dailyTicks(data) : undefined}
                        axisLine={false}
                        tickLine={false}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        tickFormatter={formatTick}
                        minTickGap={48}
                        tickMargin={10}
                    />
                    <YAxis
                        domain={["auto", "auto"]}
                        tickFormatter={formatPriceTick}
                        axisLine={false}
                        tickLine={false}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        width={72}
                    />
                    <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        separator=": "
                        formatter={(value) => [formatMoney(value, currency), "Price"]}
                        labelFormatter={(value) => tooltipDate(value, intraday)}
                    />
                    <Area
                        type="monotone"
                        dataKey="price"
                        stroke={color}
                        strokeWidth={2}
                        fill={`url(#${gradientId})`}
                        dot={false}
                    />
                </AreaChart>
            </ResponsiveContainer>
        );
    }

    return (
        <div className={`chart-wrapper${compact ? " compact" : ""}`}>
            <div className="chart-header">
                <div className="segmented" role="group" aria-label="Chart range">
                    {RANGES.map(r => (
                        <button
                            key={r}
                            onClick={() => setRange(r)}
                            className={range === r ? "active" : ""}
                            aria-pressed={range === r}
                        >
                            {r}
                        </button>
                    ))}
                </div>
            </div>

            <div className="chart-body">{body}</div>
        </div>
    );
}

export default HoldingChart;
