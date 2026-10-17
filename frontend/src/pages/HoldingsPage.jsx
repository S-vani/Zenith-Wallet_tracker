import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getHoldings} from "../services/api.js";
import HoldingsList from "../Holdings/HoldingsList.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";

import "../css/Holdings.css"

function HoldingsPage() {
    usePageTitle("Holdings");

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [holdings, setHoldings] = useState([]);
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    useEffect(() => {
        const loadHoldings = async () => {
            try {
                setLoading(true);
                setError(null);
                setHoldings(await getHoldings());
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        loadHoldings();
    }, [refreshKey]);

    let content;
    if (loading) {
        content = <div className="state-message"><div className="spinner"/>Loading your holdings…</div>;
    } else if (error) {
        content = <div className="state-message"><p className="alert-error" role="alert">{error}</p></div>;
    } else if (holdings.length === 0) {
        content = (
            <div className="state-message">
                <strong>You don't have any holdings yet</strong>
                Log a buy on the Transactions page and it will show up here.
                <Link to="/transactions" className="btn btn-primary">Add a transaction</Link>
            </div>
        );
    } else {
        content = <HoldingsList holdings={holdings}/>;
    }

    return (
        <div className="app-page">
            <header>
                <h1 className="page-headers">Holdings</h1>
                <p className="page-subtitle">Select a position to see its price history.</p>
            </header>

            <div className="holdings">
                <div className="table-header" aria-hidden="true">
                    <span>Position</span>
                    <span>Total value</span>
                    <span>Quantity</span>
                    <span>Return</span>
                    <span>Return %</span>
                    <span/>
                </div>
                {content}
            </div>
        </div>
    )
}

export default HoldingsPage
