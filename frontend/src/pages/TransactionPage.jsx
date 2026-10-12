import {useEffect, useState} from "react";
import {getTransactions} from "../services/api";
import TransactionList from "../Transactions/TransactionList";
import TransactionCreate from "../Transactions/TransactionCreate.jsx"
import TransactionFilter from "../Transactions/TransactionFilter.jsx"
import TransactionSymbolSearch from "../Transactions/TransactionSymbolSearch.jsx";
import usePageTitle from "../utils/usePageTitle.js";

import '../css/Transaction.css'

const EMPTY_FILTERS = {symbol: "", action: "", start_date: "", end_date: ""};

function TransactionsPage() {
    usePageTitle("Transactions");

    const [transactions, setTransactions] = useState([]);
    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [step, setStep] = useState("closed");
    const [symbolData, setSymbolData] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let ignore = false; // drop responses for filters the user has already changed

        getTransactions(filters)
            .then((data) => {
                if (ignore) return;
                setTransactions(data);
                setError(null);
            })
            .catch((err) => !ignore && setError(err.message))
            .finally(() => !ignore && setLoading(false));

        return () => {
            ignore = true;
        };
    }, [filters, reloadKey]);

    const changeFilters = (newFilters) => {
        setLoading(true);
        setFilters(newFilters);
    };

    const reload = () => {
        setLoading(true);
        setReloadKey((k) => k + 1);
    };

    const closeModal = () => {
        setStep("closed");
        setSymbolData(null);
    };

    // close the modal with Escape
    useEffect(() => {
        if (step === "closed") return;
        const onKey = (e) => e.key === "Escape" && closeModal();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [step]);

    const hasFilters = Object.values(filters).some(Boolean);

    let content;
    if (loading && transactions.length === 0) {
        content = <div className="state-message"><div className="spinner"/>Loading transactions…</div>;
    } else if (error) {
        content = <p className="alert-error" role="alert">{error}</p>;
    } else if (transactions.length === 0) {
        content = hasFilters ? (
            <div className="state-message">
                <strong>No transactions match these filters</strong>
                <button className="btn" onClick={() => changeFilters(EMPTY_FILTERS)}>Clear filters</button>
            </div>
        ) : (
            <div className="state-message">
                <strong>No transactions yet</strong>
                Log your first buy to start tracking your portfolio.
                <button className="btn btn-primary" onClick={() => setStep("search")}>Add transaction</button>
            </div>
        );
    } else {
        content = <TransactionList transactions={transactions}/>;
    }

    return (
        <div className="app-page">
            <header>
                <h1 className="page-headers">Transactions</h1>
                <p className="page-subtitle">Every buy and sell you've logged.</p>
            </header>

            <div className="transactions-layout">
                <section className={`transactions-list-section${loading ? " is-refreshing" : ""}`}>
                    {content}
                </section>

                <aside className="transactions-sidebar">
                    <button className="btn btn-primary transaction-button-add" onClick={() => setStep("search")}>
                        <span aria-hidden="true">+</span> Add transaction
                    </button>

                    <div className="filter-add-section">
                        <div className="filter-heading">
                            <h2 className="filter-title">Filters</h2>
                            {hasFilters && (
                                <button className="filter-clear" onClick={() => changeFilters(EMPTY_FILTERS)}>
                                    Clear all
                                </button>
                            )}
                        </div>
                        <TransactionFilter filters={filters} onFiltered={changeFilters}/>
                    </div>
                </aside>
            </div>

            {step !== "closed" && (
                <div className="transaction-create-overlay" onMouseDown={(e) => e.target === e.currentTarget && closeModal()}>
                    <div className="transaction-create-box" role="dialog" aria-modal="true" aria-labelledby="add-transaction-title">
                        <div className="modal-header">
                            <h2 id="add-transaction-title">Add transaction</h2>
                            <button className="transaction-create-close-button" onClick={closeModal} aria-label="Close">
                                <img src="/assets/close.png" alt=""/>
                            </button>
                        </div>

                        <TransactionSymbolSearch
                            onSub={(data) => {
                                setSymbolData(data);
                                setStep("create");
                            }}
                        />

                        {step === "create" && symbolData && (
                            <TransactionCreate
                                key={symbolData.api_id}
                                data={symbolData}
                                onClose={closeModal}
                                onCreated={() => {
                                    reload();
                                    closeModal();
                                }}
                            />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export default TransactionsPage;
