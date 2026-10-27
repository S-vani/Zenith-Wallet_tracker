import {useEffect, useState} from "react";
import {getPriceHistory} from "../services/api.js";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {useUser} from "../context/UserContext.jsx";
import useRefreshKey from "../native/useRefreshKey.js";
import {formatMoney, formatPrice} from "../utils/format.js";
import {
    CHART_DOWN, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, axisMoneyOptions, axisTicks, formatAxisTick, niceAxis,
    priceChartSummary, tickUnit, tooltipDate,
} from "../utils/chart.js";

const RANGES = ["1D", "1W", "1M", "1Y", "5Y"];

// `coinId`: the exact CoinGecko coin (from search or the trades), for tickers that several coins share
function HoldingChart({symbol, type, coinId = null, initialRange = "1M", compact = false}) {
    const {currency} = useUser();
    const [range, setRange] = useState(initialRange);
    // the chart on screen and the range it belongs to; while another range loads it stays visible, dimmed
    const [shown, setShown] = useState(null);
    // {range, message}: an error belongs to the range that failed, so picking another range loads it instead of
    // showing the old error, and "Try again" (attempt) loads the failed one again
    const [failure, setFailure] = useState(null);
    const [attempt, setAttempt] = useState(0);
    // set once a "5Y" answer turned out shorter (CoinGecko stops at a year), so the 5Y button can say so
    const [fiveYearNote, setFiveYearNote] = useState(null);
    const refreshKey = useRefreshKey(); // app only: pull to refresh reloads in place

    useEffect(() => {
        let ignore = false;

        getPriceHistory(symbol, type, range, coinId)
            .then((res) => {
                if (ignore) return;
                setShown({
                    range,
                    data: res.data.map(p => ({time: p.time, price: p.price})),
                    // the range the prices really cover and why, when less than asked for
                    covered: res.covered_range ?? null,
                    note: res.note ?? null,
                });
                if (range === "5Y") setFiveYearNote(res.covered_range && res.note ? res.note : null);
                setFailure(null);
            })
            .catch((err) => {
                if (!ignore) setFailure({range, message: err.message});
            });

        return () => {
            ignore = true;
        };
    }, [symbol, range, type, coinId, refreshKey, attempt]);

    const error = failure?.range === range ? failure.message : null;
    const retry = () => {
        setFailure(null);
        setAttempt((n) => n + 1);
    };
    const data = shown?.data ?? [];
    const pending = !error && shown?.range !== range; // a new range is loading
    const isUp = data.length > 1 && data[data.length - 1].price >= data[0].price;
    const color = isUp ? CHART_UP : CHART_DOWN;
    const gradientId = `holdingFill-${type}-${symbol}`;
    const intraday = shown?.range === "1D" || shown?.range === "1W";
    const unit = tickUnit(data);
    const prices = data.map((d) => d.price);
    // round ticks a nice step apart (like the dashboard's), with no headroom so the line still fills the chart;
    // the add-trade sheet's short chart gets fewer of them so the labels don't crowd
    const nice = niceAxis(prices, compact ? 4 : 5);
    // a tick step under 1e-6 (coins like PEPE) currently rounds every tick to 0, so those keep recharts' own axis
    const yAxis = nice && nice.ticks.every((t, i) => i === 0 || t > nice.ticks[i - 1]) ? nice : null;
    const priceOptions = yAxis ? axisMoneyOptions(yAxis.ticks, yAxis.step) : axisMoneyOptions(prices);
    const label = String(symbol).toUpperCase();

    const failed = error && (!shown || shown.range !== range);
    const charted = Boolean(shown) && !failed && data.length > 0;

    let body;
    if (!shown && !error) {
        // a spinner alone says nothing to a screen reader
        body = (
            <div className="state-message" role="status">
                <div className="spinner" aria-hidden="true"/>
                <span className="visually-hidden">Loading {label} price chart…</span>
            </div>
        );
    } else if (failed) {
        body = (
            <div className="state-message">
                <p className="alert-error" role="alert">{error}</p>
                <button type="button" className="btn" onClick={retry}>Try again</button>
            </div>
        );
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
                        domain={yAxis?.domain ?? ["auto", "auto"]}
                        ticks={yAxis?.ticks}
                        interval={0}
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
                            title={r === "5Y" && fiveYearNote ? fiveYearNote : undefined}
                        >
                            {r}
                        </button>
                    ))}
                </div>
            </div>

            {/* the chart is a picture to a screen reader, so it gets the numbers as text */}
            {charted && (
                <p className="chart-sr-summary">
                    {priceChartSummary(label, shown.range, shown.covered, data, (v) => formatPrice(v, currency))}
                </p>
            )}
            <div className={`chart-body${pending && shown ? " is-updating" : ""}`} aria-busy={pending}>{body}</div>
            {/* e.g. CoinGecko's "5Y" only goes back a year: say so instead of letting the axis imply 5 years */}
            {charted && shown.note && <p className="chart-range-note">{shown.note}</p>}
        </div>
    );
}

export default HoldingChart;
