import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getHoldings} from "../services/api.js";
import HoldingsList from "../Holdings/HoldingsList.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";

import "../css/Holdings.css"

function HoldingsPage() {
    usePageTitle("Holdings");

    const [error, setError] = useState(null);
    const [holdings, setHoldings] = useState(null); // null until the first load finishes
    const [attempt, setAttempt] = useState(0); // bumped by "Try again"
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    useEffect(() => {
        let ignore = false;

        // a refresh swaps the numbers in place: the list stays mounted, so an open chart and the scroll position
        // are kept
        getHoldings()
            .then((data) => {
                if (ignore) return;
                setHoldings(data);
                setError(null);
            })
            .catch((err) => {
                if (!ignore) setError(err.message);
            });

        return () => {
            ignore = true;
        };
    }, [refreshKey, attempt]);

    const retry = () => {
        setError(null); // back to the spinner (or the current list) while it tries again
        setAttempt((n) => n + 1);
    };

    const errorAlert = (
        <div className="alert-error alert-retry holdings-refresh-error" role="alert">
            <span>{error}</span>
            <button type="button" className="btn" onClick={retry}>Try again</button>
        </div>
    );

    let content;
    if (holdings === null) {
        content = error
            ? <div className="state-message">{errorAlert}</div>
            : <div className="state-message"><div className="spinner"/>Loading your holdings…</div>;
    } else if (holdings.length === 0) {
        content = (
            <div className="state-message">
                <strong>You don't have any holdings yet</strong>
                Log a buy on the Transactions page and it will show up here.
                <Link to="/transactions" className="btn btn-primary">Add a transaction</Link>
            </div>
        );
    } else {
        content = (
            <>
                {error && errorAlert}
                <HoldingsList holdings={holdings}/>
            </>
        );
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
