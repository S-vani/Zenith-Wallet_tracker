import {useEffect, useState} from "react";
import {getPriceHistory} from "../services/api.js";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {useUser} from "../context/UserContext.jsx";
import useRefreshKey from "../native/useRefreshKey.js";
import {formatMoney, formatPrice} from "../utils/format.js";
import {
    CHART_DOWN, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, axisMoneyOptions, axisTicks, formatAxisTick, tickUnit,
    tooltipDate,
} from "../utils/chart.js";

const RANGES = ["1D", "1W", "1M", "1Y", "5Y"];

function HoldingChart({symbol, type, initialRange = "1M", compact = false}) {
    const {currency} = useUser();
    const [range, setRange] = useState(initialRange);
    // the chart on screen and the range it belongs to; while another range loads it stays visible, dimmed
    const [shown, setShown] = useState(null);
    const [error, setError] = useState(null);
    const refreshKey = useRefreshKey(); // app only: pull to refresh reloads in place

    useEffect(() => {
        let ignore = false;

        getPriceHistory(symbol, type, range)
            .then((res) => {
                if (ignore) return;
                setShown({range, data: res.data.map(p => ({time: p.time, price: p.price}))});
                setError(null);
            })
            .catch((err) => {
                if (!ignore) setError(err.message);
            });

        return () => {
            ignore = true;
        };
    }, [symbol, range, type, refreshKey]);

    const data = shown?.data ?? [];
    const pending = !error && shown?.range !== range; // a new range is loading
    const isUp = data.length > 1 && data[data.length - 1].price >= data[0].price;
    const color = isUp ? CHART_UP : CHART_DOWN;
    const gradientId = `holdingFill-${type}-${symbol}`;
    const intraday = shown?.range === "1D" || shown?.range === "1W";
    const unit = tickUnit(data);
    const priceOptions = axisMoneyOptions(data.map((d) => d.price));
    const label = String(symbol).toUpperCase();

    let body;
    if (!shown && !error) {
        body = <div className="state-message"><div className="spinner"/></div>;
    } else if (error && (!shown || shown.range !== range)) {
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
                        ticks={axisTicks(data, unit)}
                        axisLine={false}
                        tickLine={false}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        tickFormatter={(v) => formatAxisTick(v, unit)}
                        minTickGap={24}
                        tickMargin={10}
                    />
                    <YAxis
                        domain={["auto", "auto"]}
                        tickFormatter={(v) => formatMoney(v, currency, priceOptions)}
                        axisLine={false}
                        tickLine={false}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        width={76}
                    />
                    <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        separator=": "
                        formatter={(value) => [formatPrice(value, currency), "Price"]}
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
                <h3 className="chart-title">
                    {label} price <span className="chart-title-note">(per {type === "crypto" ? "coin" : "share"})</span>
                </h3>
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

            <div className={`chart-body${pending && shown ? " is-updating" : ""}`} aria-busy={pending}>{body}</div>
        </div>
    );
}

export default HoldingChart;
