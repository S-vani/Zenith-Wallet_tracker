import {Link} from "react-router-dom";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {formatMoney} from "../utils/format.js";
import {
    CHART_DOWN, CHART_INVESTED, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, axisMoneyOptions, axisTicks,
    formatAxisTick, tickUnit, tooltipDate,
} from "../utils/chart.js";
import {dashboardChartSummary} from "./dashboardText.js";

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
    const valueOptions = axisMoneyOptions(data.flatMap((d) => (hasInvested ? [d.value, d.invested] : [d.value])));

    let body;
    if (error) {
        // not role="alert": the page announces the error once, next to its Try again button
        body = <div className="state-message"><p className="alert-error">{error}</p></div>;
    } else if (!entry) {
        body = (
            <div className="state-message">
                <div className="spinner"/>
                Building your portfolio history…
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
                <AreaChart data={data} margin={{top: 8, right: 8, left: 0, bottom: 0}}>
                    <defs>
                        <linearGradient id="dashboardFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={color} stopOpacity={0.3}/>
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
                        domain={["auto", "auto"]}
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
                        dot={false}
                        activeDot={{r: 4, fill: color, strokeWidth: 0}}
                    />
                    {hasInvested && (
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
                {charted && hasInvested && (
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
                    {hasInvested
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
