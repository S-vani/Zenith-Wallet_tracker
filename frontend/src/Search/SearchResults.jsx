import { useState } from "react";
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip, XAxis } from "recharts";
import { getPriceHistory } from "../services/api.js";

function SearchResults({ results }) {
    const [expandedId, setExpandedId] = useState(null);
    const [chartData, setChartData] = useState({});
    const [loadingChart, setLoadingChart] = useState(false);

    const handleSelect = async (result) => {
        const id = result.api_id;

        if (expandedId === id) {
            setExpandedId(null);
            return;
        }

        setExpandedId(id);

        if (chartData[id]) return;

        setLoadingChart(true);
        try {
            const res = await getPriceHistory(id, result.type, "1D");

            const formatted = res.data.map((point) => ({
                time: point.time,
                price: point.price,
                label: new Date(point.time).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                }),
            }));

            setChartData((prev) => ({ ...prev, [id]: formatted }));
        } catch (err) {
            console.error("Failed to load daily price:", err);
            setChartData((prev) => ({ ...prev, [id]: [] }));
        } finally {
            setLoadingChart(false);
        }
    };

    return (
        <div className="search-results-list">
            {results.map((result) => {
                const isExpanded = expandedId === result.api_id;
                const isPositive = result.change_pct >= 0;
                const data = chartData[result.api_id];

                return (
                    <div key={result.api_id} className="search-result-wrapper">
                        <div className="search-result-item" onClick={() => handleSelect(result)}>
                            <div className="search-result-left">
                                <div className="search-result-info">
                                    <span className="search-result-symbol">{result.symbol}</span>
                                    <span className="search-result-type">{result.type}</span>
                                </div>
                            </div>

                            <div className="search-result-right">
                                <span className="search-result-price">
                                    ${result.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                                </span>
                                <span className={`search-result-change ${isPositive ? "positive" : "negative"}`}>
                                    {isPositive ? "+" : ""}
                                    {result.change_pct.toFixed(2)}%
                                </span>
                            </div>
                        </div>

                        {isExpanded && (
                            <div className="search-result-chart-box">
                                {loadingChart && !data ? (
                                    <div className="loading-search">Loading chart...</div>
                                ) : data?.length ? (
                                    <ResponsiveContainer width="100%" height={140}>
                                        <LineChart data={data}>
                                            <XAxis
                                                dataKey="label"
                                                tick={{ fill: "#6b7280", fontSize: 10 }}
                                                interval={Math.floor(data.length / 6)}
                                                axisLine={{ stroke: "#0f1725" }}
                                                tickLine={false}
                                            />
                                            <YAxis domain={["auto", "auto"]} hide />
                                            <Tooltip
                                                contentStyle={{
                                                    background: "#0b1220",
                                                    border: "0.05rem solid #0f1725",
                                                    borderRadius: "0.5rem",
                                                    color: "#f5f7ff",
                                                }}
                                                labelStyle={{ color: "#9aa0a6" }}
                                                formatter={(value) => [`$${value.toFixed(2)}`, "Price"]}
                                            />
                                            <Line
                                                type="monotone"
                                                dataKey="price"
                                                stroke={isPositive ? "#22c55e" : "#ef4444"}
                                                strokeWidth={2}
                                                dot={false}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                ) : (
                                    <div className="error-search">No chart data available.</div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

export default SearchResults;
