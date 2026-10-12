import {useEffect, useState} from "react";

function TransactionFilter({filters, onFiltered}) {
    // the symbol box is debounced so we don't hit the api on every keystroke
    const [symbol, setSymbol] = useState(filters.symbol);
    const [syncedSymbol, setSyncedSymbol] = useState(filters.symbol);

    // keep the box in sync when the filters are changed from outside (e.g. "Clear filters")
    if (filters.symbol !== syncedSymbol) {
        setSyncedSymbol(filters.symbol);
        setSymbol(filters.symbol);
    }

    useEffect(() => {
        if (symbol === filters.symbol) return;
        const timeout = setTimeout(() => onFiltered({...filters, symbol}), 300);
        return () => clearTimeout(timeout);
    }, [symbol, filters, onFiltered]);

    const handleChange = (e) => {
        onFiltered({
            ...filters,
            [e.target.name]: e.target.value
        })
    };

    return (
        <div className="filter-container">
            <form className="filter-form" onSubmit={(e) => e.preventDefault()}>

                <div className="filter-group">
                    <label className="filter-label" htmlFor="filter-symbol">
                        Symbol
                    </label>

                    <input
                        id="filter-symbol"
                        className="filter-input"
                        name="symbol"
                        type="search"
                        placeholder="AAPL, BTC, TSLA..."
                        value={symbol}
                        onChange={(e) => setSymbol(e.target.value)}
                        autoComplete="off"
                    />
                </div>

                <div className="filter-group">
                    <label className="filter-label" htmlFor="filter-action">
                        Action
                    </label>

                    <select
                        id="filter-action"
                        className="filter-select"
                        name="action"
                        value={filters.action}
                        onChange={handleChange}
                    >
                        <option value="">All</option>
                        <option value="BUY">Buy</option>
                        <option value="SELL">Sell</option>
                    </select>
                </div>

                <div className="filter-group">
                    <label className="filter-label" htmlFor="filter-start">
                        Start date
                    </label>

                    <input
                        id="filter-start"
                        className="filter-input filter-date-input"
                        type="date"
                        name="start_date"
                        value={filters.start_date}
                        max={filters.end_date || undefined}
                        onChange={handleChange}
                    />
                </div>

                <div className="filter-group">
                    <label className="filter-label" htmlFor="filter-end">
                        End date
                    </label>

                    <input
                        id="filter-end"
                        className="filter-input filter-date-input"
                        type="date"
                        name="end_date"
                        value={filters.end_date}
                        min={filters.start_date || undefined}
                        onChange={handleChange}
                    />
                </div>

            </form>
            {filters.start_date && filters.end_date && filters.end_date < filters.start_date && (
                <p className="filter-hint">End date is before the start date.</p>
            )}
        </div>
    )
}

export default TransactionFilter
