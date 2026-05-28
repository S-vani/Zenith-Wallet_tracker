import {useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";
import TransactionSymbolList from "./TransactionSymbolList.jsx";

function TransactionSymbolSearch({onSub}) {
    const [type, setType] = useState("")
    const [symbol, setSymbol] = useState("");
    const [results, setResults] = useState([]);
    const [showSymbols, setShowSymbols] = useState(false)
    const [selectedSymbol, setSelectedSymbol] = useState(null);
    const [loading, setLoading] = useState(false)

    const getPlaceholder = () => {
        if (type === "stock") {
            return "AAPL, NVDA, GOOG"
        } else if (type === "crypto") {
            return "BTC, SOL, ETH"
        } else {
            return "Select a type above"
        }
    }

    const onSubSymbols = (data, selected) => {
        onSub(data);
        setShowSymbols(false)
        setSelectedSymbol(selected)
    }


    const handleChange = (e) => {
        setSymbol(e.target.value)
    }

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true)

        if (type === "stock") {
            const data = await searchStock(symbol)
            setResults(data)
            setShowSymbols(true)
        } else if (type === "crypto") {
            const data = await searchCrypto(symbol)
            setResults(data)
            setShowSymbols(true)
        }
        setLoading(false)

    };

    return (
        <div className="transaction-symbol-wrapper">
            <h2>Search</h2>
            <div className="search-buttons">
                <button
                    className={type === "stock" ? "search-button active" : "search-button"}
                    onClick={() => setType("stock")}>
                    Stock
                </button>
                <button
                    className={type === "crypto" ? "search-button active" : "search-button"}
                    onClick={() => setType("crypto")}>
                    Crypto
                </button>
            </div>
            <form className="symbol-search-form" onSubmit={handleSubmit}>
                <input
                    className="symbol-search-input"
                    name="symbol"
                    placeholder={getPlaceholder()}
                    onChange={handleChange}
                    autoComplete="off"/>


                <button className={type === "" ? "search-button red" : "search-button"} type="submit">Search</button>
            </form>

            {loading && (
                <h3 className="loading-search">Loading...</h3>
            )}

            {showSymbols && (
                <TransactionSymbolList
                    data={results}
                    onSub={onSubSymbols}
                />
            )}

            {selectedSymbol !== null && (
                <div className="transaction-symbol-item-wrapper">
                    <div className="symbol">
                        <span className="symbol-image">
                            {
                                selectedSymbol.image !== "" && (
                                    <img src={selectedSymbol.image} alt=""/>
                                )}
                        </span>

                        <span className="symbol-text">{selectedSymbol.symbol}</span>
                    </div>

                    <div className="price">
                        ${Number(selectedSymbol.price).toFixed(2)}
                    </div>

                    <div className="type">
                        {selectedSymbol.type}
                    </div>

                    <div className="change">
                        <span>
                            ${Number(selectedSymbol.change).toFixed(2)}
                        </span>
                        <span>
                            ({selectedSymbol.change_pct.toFixed(2)}%)
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}

export default TransactionSymbolSearch
