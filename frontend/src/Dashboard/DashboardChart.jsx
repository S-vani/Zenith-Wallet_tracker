import {useEffect, useState} from "react";
import {getPortfolioHistory} from "../services/api.js";
import {LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";

const RANGE_DAYS = {day: 1, week: 7, month: 31, year: 365, all: 3650};

function DashboardChart({range}) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);

    const loadDashboardChart = async (selectedRange) => {
        setLoading(true);
        const res = await getPortfolioHistory(selectedRange);
        setData(res);
        setLoading(false);
    };

    useEffect(() => {
        loadDashboardChart(RANGE_DAYS[range] ?? 1);
    }, [range]);

    return (
        <div className="chart-wrapper">

            <div className="chart-body">
                {loading ? (
                    <p className="loading-chart">Loading…</p>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={data} margin={{top: 4, right: 4, left: -20, bottom: 0}}>
                            <XAxis
                                dataKey="time"
                                tick={{fill: "#6b7280", fontSize: 11}}
                                axisLine={{stroke: "rgba(255,255,255,0.06)"}}
                                tickLine={false}
                                tickFormatter={(v) =>
                                    new Date(v).toLocaleDateString(undefined, {
                                        month: "short",
                                        day: "numeric"
                                    })
                                }
                            />
                            <YAxis
                                domain={["auto", "auto"]}
                                tick={{fill: "#6b7280", fontSize: 11}}
                                axisLine={false}
                                tickLine={false}
                            />
                            <Tooltip
                                contentStyle={{
                                    background: "#0f1520",
                                    border: "1px solid rgba(255,255,255,0.1)",
                                    borderRadius: "0.625rem",
                                    fontSize: "0.8rem",
                                    color: "#f5f7ff",
                                }}
                                labelFormatter={(value) => {
                                    const date = new Date(value);
                                    return date.toLocaleDateString(undefined, {
                                        month: "short",
                                        day: "numeric",
                                        year: "numeric",
                                        hour: "2-digit",
                                        minute: "2-digit",
                                        hour12: true
                                    });
                                }}
                                cursor={{stroke: "rgba(59,130,246,0.3)", strokeWidth: 1}}
                            />
                            <Line
                                type="monotone"
                                dataKey="value"
                                stroke="#3b82f6"
                                strokeWidth={2}
                                dot={false}
                                activeDot={{r: 4, fill: "#3b82f6", strokeWidth: 0}}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
}

export default DashboardChart;
