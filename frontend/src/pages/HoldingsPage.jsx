import {useEffect, useState} from "react";
import {getHoldings} from "../services/api.js";
import HoldingsList from "../Holdings/HoldingsList.jsx";

import "../css/Holdings.css"

function HoldingsPage() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [holdings, setHoldings] = useState([]);

    const loadHoldings = async () => {
        try {
            setLoading(true);
            setError(null);

            const data = await getHoldings();
            setHoldings(data)
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadHoldings();
    }, []);

    return (
        <div>
            <h1 className="holdings-header">Holdings</h1>
            <div className="holdings">
                <div className="table-header">
                    <span>Positions</span>
                    <span>Total value</span>
                    <span>Quantity</span>
                    <span>Return</span>
                    <span>Return %</span>
                </div>
                {loading && <p className="loading-holdings">Loading...</p>}
                {error && <p className="error-holdings">{error}</p>}
                <HoldingsList holdings={holdings}/>
            </div>
        </div>

    )
}

export default HoldingsPage
