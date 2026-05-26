import {useEffect, useState} from "react";
import {getPortfolioHistory, getUser} from "../services/api.js";
import {LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";

function DashboardChart({range}) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [diffDays, setDiffDays] = useState(null);

    useEffect(() => {
        const loadUser = async () => {
            const user_info = await getUser();

            const created = new Date(user_info.date_joined);
            const now = new Date();

            setDiffDays(
                Math.ceil((now - created) / (1000 * 60 * 60 * 24))
            );
        };

        loadUser();
    }, []);

    const getRangeValue = () => ({
        day: 1,
        week: 7,
        month: 31,
        year: 365,
        all: diffDays
    });

    const loadDashboardChart = async (selectedRange) => {
        setLoading(true);

        const res = await getPortfolioHistory(selectedRange);
        setData(res);

        setLoading(false);
    };

    useEffect(() => {
        if (range === "all" && diffDays == null) return;

        const ranges = getRangeValue();

        loadDashboardChart(ranges[range] ?? 1);
    }, [range, diffDays]);

    return (
        <div className="chart-wrapper-dashboard">

            <div className="chart-body">
                {loading ? (
                    <p className="loading-chart">Graphing chart...</p>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={data} margin={{top: 4, right: 5, left: 0, bottom: 0}}>
                            <XAxis
                                dataKey="time"
                                interval={16}
                                tickMargin={10}
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
                                tickMargin={0}
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
