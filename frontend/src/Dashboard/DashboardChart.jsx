import {Link} from "react-router-dom";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {formatMoney} from "../utils/format.js";
import {
    CHART_DOWN, CHART_INVESTED, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, axisMoneyOptions, axisTicks,
    formatAxisTick, niceAxis, tickUnit, tooltipDate,
} from "../utils/chart.js";
import {dashboardChartSummary} from "./dashboardText.js";
import ChartSkeleton from "../components/ChartSkeleton.jsx";

// The values' own range with 15% room above and below (not below 0 for money that never went negative), so a small
// move fills the chart instead of a share of the whole amount
function paddedRange(values) {
    const numbers = values.map(Number).filter(Number.isFinite);
    if (numbers.length === 0) return values;
    const min = Math.min(...numbers);
    const max = Math.max(...numbers);
    const pad = (max - min) * 0.15;
    return [min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad];
}

// "Now": a dot on the latest point that appears once the line has drawn in and pulses twice (CSS .now-dot), in the
// gain / loss colour. Every other point draws nothing.
function NowDot({cx, cy, index, last, color}) {
    if (index !== last || !Number.isFinite(cx) || !Number.isFinite(cy)) return <g/>;
    return (
        <g className="now-dot" aria-hidden="true">
            <circle className="now-dot-pulse" cx={cx} cy={cy} r={4} fill={color}/>
            <circle cx={cx} cy={cy} r={4} fill={color} stroke="#0b1220" strokeWidth={2}/>
        </g>
    );
}

// `entry` is one range's {days, stats, chart}, loaded by the page; `updating` dims it while another range loads
function DashboardChart({entry, updating = false, currency, error}) {
    const data = entry?.chart ?? [];
    const days = entry?.days ?? 1;
    const hasValues = data.some((d) => d.value > 0);
    // older saved charts (the app's offline copy) have no invested amounts: then only the value line is drawn
    const hasInvested = data.some((d) => Number.isFinite(d.invested));
    // the value line includes money added and taken out, so its colour follows the period's return shown in the
    // card above (never the line's own start vs end, which deposits make look like a gain)
    const color = Number(entry?.stats?.curr_timeperiod) >= 0 ? CHART_UP : CHART_DOWN;
    const unit = tickUnit(data);
    // A day or a week: the value line alone on its own scale, the way finance apps chart intraday moves. With the
    // invested line on the same axis a 1% day was a flat line far above it. From a month up both lines are drawn.
    const showInvested = hasInvested && days > 7;
    const axisValues = data.flatMap((d) => (showInvested ? [d.value, d.invested] : [d.value]));
    // round ticks a nice step apart (CA$0 / 10K / 20K / 30K), labelled with just the decimals that step needs
    // with ~10% headroom around the data so the value and invested lines sit closer together instead of the gap
    // between them filling the whole height (a tight axis made a 15% gain look enormous)
    const yAxis = showInvested ? niceAxis(axisValues, 5, {headroom: 0.1}) : niceAxis(paddedRange(axisValues), 5);
    const valueOptions = yAxis ? axisMoneyOptions(yAxis.ticks, yAxis.step) : axisMoneyOptions(axisValues);

    let body;
    if (error) {
        // not role="alert": the page announces the error once, next to its Try again button
        body = <div className="state-message"><p className="alert-error">{error}</p></div>;
    } else if (!entry) {
        body = <ChartSkeleton label="Building your portfolio history…"/>;
    } else if (!hasValues && entry.stats?.has_trades) {
        // everything was sold before this period, or nothing held has a price: not a new account
        body = (
            <div className="state-message">
                <strong>Nothing to chart for this period</strong>
                You didn't hold anything with a known price during it. Your past trades are still on the
                Transactions page.
                <Link to="/transactions" className="btn">See your transactions</Link>
            </div>
        );
    } else if (!hasValues) {
        body = (
            <div className="state-message">
                <strong>No history yet</strong>
                Add a transaction and your portfolio value will be charted here.
                <Link to="/transactions" className="btn btn-primary">Add your first transaction</Link>
            </div>
        );
    } else {
        body = (
            <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_DIMENSION}>
                {/* keyed by range: a new range draws in fresh instead of morphing through shapes that mean nothing
                    (a 1D line bending into a 1Y one); a refresh of the same range still updates in place */}
                <AreaChart key={entry.range} data={data} margin={{top: 8, right: 8, left: 0, bottom: 0}}>
                    <defs>
                        <linearGradient id="dashboardFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={color} stopOpacity={0.18}/>
                            <stop offset="100%" stopColor={color} stopOpacity={0}/>
                        </linearGradient>
                    </defs>
                    <XAxis
                        dataKey="time"
                        ticks={axisTicks(data, unit)}
                        minTickGap={24}
                        tickMargin={10}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        axisLine={{stroke: "rgba(255,255,255,0.06)"}}
                        tickLine={false}
                        tickFormatter={(v) => formatAxisTick(v, unit)}
                    />
                    <YAxis
                        width={76}
                        domain={yAxis?.domain ?? ["auto", "auto"]}
                        ticks={yAxis?.ticks}
                        interval={0}
                        tick={{fill: "#8b93a1", fontSize: 11}}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v) => formatMoney(v, currency, valueOptions)}
                    />
                    <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        separator=": "
                        formatter={(value, name) => [formatMoney(value, currency), name]}
                        labelFormatter={(value) => tooltipDate(value, days <= 7)}
                        itemSorter={(item) => (item.dataKey === "value" ? 0 : 1)} // same order as the legend
                        cursor={{stroke: "rgba(59,130,246,0.3)", strokeWidth: 1}}
                    />
                    <Area
                        type="monotone"
                        dataKey="value"
                        name="Value"
                        stroke={color}
                        strokeWidth={2}
                        fill="url(#dashboardFill)"
                        dot={(props) => <NowDot key={props.index} {...props} last={data.length - 1} color={color}/>}
                        activeDot={{r: 4, fill: color, strokeWidth: 0}}
                        animationDuration={800}
                        animationEasing="ease-out"
                    />
                    {showInvested && (
                        <Area
                            type="monotone"
                            dataKey="invested"
                            name="Invested"
                            stroke={CHART_INVESTED}
                            strokeOpacity={0.7}
                            strokeWidth={1.5}
                            strokeDasharray="5 4"
                            fill="none"
                            dot={false}
                            activeDot={{r: 3, fill: CHART_INVESTED, strokeWidth: 0}}
                            animationBegin={120}
                            animationDuration={800}
                            animationEasing="ease-out"
                        />
                    )}
                </AreaChart>
            </ResponsiveContainer>
        );
    }

    const charted = hasValues && !error;

    return (
        <figure className="dashboard-chart">
            {/* the chart is a picture to a screen reader, so it gets the numbers as text */}
            {charted && <p className="chart-sr-summary">{dashboardChartSummary(data, entry?.range, currency)}</p>}
            <div className="chart-wrapper-dashboard">
                {charted && showInvested && (
                    <div className="chart-legend" aria-hidden="true">
                        <span className="chart-legend-item">
                            <span className="chart-legend-swatch" style={{borderColor: color}}/>Value
                        </span>
                        <span className="chart-legend-item">
                            <span className="chart-legend-swatch dashed"/>Invested
                        </span>
                    </div>
                )}
                <div className={`chart-body${updating ? " is-updating" : ""}`} aria-busy={updating}>{body}</div>
            </div>
            {charted && (
                <figcaption className="chart-note">
                    {showInvested
                        ? "The solid line is your portfolio's value and the dashed line is what you paid for what " +
                        "you still hold, so buys and sells move both and the gap between them is your unrealized " +
                        "gain or loss. The return above leaves buys and sells out."
                        : "The line is your total portfolio value, so buys and sells move it too. The return above " +
                        "leaves them out."}
                </figcaption>
            )}
        </figure>
    );
}

export default DashboardChart;
