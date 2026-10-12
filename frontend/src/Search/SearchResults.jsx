import { useState } from "react";
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip, XAxis } from "recharts";
import { getPriceHistory } from "../services/api.js";
import { useUser } from "../context/UserContext.jsx";
import { formatMoney, formatPercent } from "../utils/format.js";

function SearchResults({ results }) {
    const [expandedId, setExpandedId] = useState(null);
    const [chartData, setChartData] = useState({});
    const [loadingChart, setLoadingChart] = useState(false);
    const { currency } = useUser();

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
            const res = await getPriceHistory(result.symbol, result.type, "1D");

            const formatted = res.data.map((point) => ({
                time: new Date(point.time).getTime(),
                price: point.price,
            }));

            setChartData((prev) => ({ ...prev, [id]: formatted }));
        } catch {
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
                        <button className={`search-result-item${isExpanded ? " open" : ""}`}
                                onClick={() => handleSelect(result)} aria-expanded={isExpanded}>
                            <div className="search-result-left">
                                {result.image && <img className="search-result-image" src={result.image} alt=""/>}
                                <div className="search-result-info">
                                    <span className="search-result-symbol">{result.symbol}</span>
                                    <span className="search-result-type">{result.type}</span>
                                </div>
                            </div>

                            <div className="search-result-right">
                                <span className="search-result-price">
                                    {formatMoney(result.price, currency, { maximumFractionDigits: result.price < 1 ? 6 : 2 })}
                                </span>
                                <span className={`search-result-change ${isPositive ? "positive" : "negative"}`}>
                                    {formatPercent(result.change_pct)} today
                                </span>
                            </div>
                        </button>

                        {isExpanded && (
                            <div className="search-result-chart-box">
                                {loadingChart && !data ? (
                                    <div className="state-message"><div className="spinner"/></div>
                                ) : data?.length ? (
                                    <ResponsiveContainer width="100%" height={140} initialDimension={{ width: 1, height: 140 }}>
                                        <LineChart data={data}>
                                            <XAxis
                                                dataKey="time"
                                                type="number"
                                                domain={["dataMin", "dataMax"]}
                                                scale="time"
                                                tickFormatter={(t) =>
                                                    new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                                                }
                                                tick={{ fill: "#6b7280", fontSize: 10 }}
                                                axisLine={{ stroke: "#0f1725" }}
                                                tickLine={false}
                                                minTickGap={40}
                                            />
                                            <YAxis domain={["auto", "auto"]} hide />
                                            <Tooltip
                                                contentStyle={{
                                                    background: "#0b1220",
                                                    border: "0.05rem solid #0f1725",
                                                    borderRadius: "0.5rem",
                                                    color: "#f5f7ff",
                                                }}
                                                labelFormatter={(t) => new Date(t).toLocaleTimeString()}
                                                separator=": "
                                                formatter={(value) => [formatMoney(value, currency), "Price"]}
                                            />
                                            <Line type="monotone" dataKey="price" stroke={isPositive ? "#22c55e" : "#ef4444"} strokeWidth={2} dot={false} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                ) : (
                                    <div className="state-message">No chart data available right now.</div>
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
