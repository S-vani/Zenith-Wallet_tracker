import {Link} from "react-router-dom";
import {AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";
import {formatMoney} from "../utils/format.js";
import {
    CHART_DOWN, CHART_UP, INITIAL_DIMENSION, TOOLTIP_STYLE, axisMoneyOptions, axisTicks, formatAxisTick, tickUnit,
    tooltipDate,
} from "../utils/chart.js";

// `entry` is one range's {days, stats, chart}, loaded by the page; `updating` dims it while another range loads
function DashboardChart({entry, updating = false, currency, error}) {
    const data = entry?.chart ?? [];
    const days = entry?.days ?? 1;
    const hasValues = data.some((d) => d.value > 0);
    // the value line includes money added and taken out, so its colour follows the period's return shown in the
    // card above (never the line's own start vs end, which deposits make look like a gain)
    const color = Number(entry?.stats?.curr_timeperiod) >= 0 ? CHART_UP : CHART_DOWN;
    const unit = tickUnit(data);
    const valueOptions = axisMoneyOptions(data.map((d) => d.value));

    let body;
    if (error) {
        body = <div className="state-message"><p className="alert-error" role="alert">{error}</p></div>;
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
        <figure className="dashboard-chart">
            <div className="chart-wrapper-dashboard">
                <div className={`chart-body${updating ? " is-updating" : ""}`} aria-busy={updating}>{body}</div>
            </div>
            {hasValues && !error && (
                <figcaption className="chart-note">
                    The line is your total portfolio value, so buys and sells move it too. The return above leaves
                    them out.
                </figcaption>
            )}
        </figure>
    );
}

export default DashboardChart;
