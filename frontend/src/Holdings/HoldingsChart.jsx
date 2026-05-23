import {useEffect, useState} from "react";
import {getPriceHistory} from "../services/api.js";
import {LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer} from "recharts";

function HoldingChart({symbol, type}) {
    const [range, setRange] = useState("1M");
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const load = async () => {
            setLoading(true);

            const res = await getPriceHistory(symbol, type, range);

            // transform backend → recharts format
            const formatted = res.data.map(p => ({
                time: p.time,
                price: p.price
            }));

            setData(formatted);
            setLoading(false);
        };

        load();
    }, [symbol, range, type]);

    const ranges = ["1D", "1W", "1M", "1Y", "5Y"];

    return (
        <div className="chart-wrapper">
            <div className="chart-header">
                <div className="range-buttons">
                    {ranges.map(r => (
                        <button
                            key={r}
                            onClick={() => setRange(r)}
                            className={`range-btn ${range === r ? "active" : ""}`}
                        >
                            {r}
                        </button>
                    ))}
                </div>
            </div>

            <div className="chart-body">
                {loading ? (
                    <div className="loading-chart">Loading...</div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                            data={data}
                            margin={{ top: 10, right: 20, left: 30, bottom: 20 }}
                        >
                            <XAxis
                                dataKey="time"
                                axisLine={false}
                                tickLine={false}
                                stroke="#8a8a8a"
                                tickFormatter={(v) =>
                                    new Date(v).toLocaleDateString(undefined, {
                                        month: "short",
                                        day: "numeric"
                                    })
                                }
                                ticks={data
                                    .filter((_, i) => i % Math.ceil(data.length / 6) === 0)
                                    .map(d => d.time)
                                }
                                interval="preserveStartEnd"
                                minTickGap={40}
                                tickMargin={20}
                            />
                            <YAxis
                                domain={["dataMin", "dataMax"]}
                                tickFormatter={(value) => value.toFixed(2)}
                                axisLine={false}
                                tickLine={false}
                                stroke="#8a8a8a"
                                tickMargin={30}
                                width={100}
                            />
                            <Tooltip
                                contentStyle={{
                                    backgroundColor: "#1f1f1f",
                                    border: "1px solid #3d3d3d",
                                    borderRadius: "12px",
                                    color: "#f5f7ff"
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
                            />
                            <Line
                                type="monotone"
                                dataKey="price"
                                stroke="#3b82f6"
                                strokeWidth={2.5}
                                dot={false}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
}

export default HoldingChart;
