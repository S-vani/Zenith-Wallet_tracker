import {useEffect, useRef, useState} from "react";
import {getTransactions} from "../services/api";
import useRefreshKey from "../native/useRefreshKey.js";
import TransactionList from "../Transactions/TransactionList";
import TransactionCreate from "../Transactions/TransactionCreate.jsx"
import TransactionFilter from "../Transactions/TransactionFilter.jsx"
import TransactionSymbolSearch from "../Transactions/TransactionSymbolSearch.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useDialog from "../Transactions/useDialog.js";

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
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app
    const [filtersOpen, setFiltersOpen] = useState(false); // only matters on phones, where filters start collapsed
    const dialogRef = useRef(null);
    const addButtonRef = useRef(null);

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
    }, [filters, reloadKey, refreshKey]);

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

    const hasFilters = Object.values(filters).some(Boolean);
    const activeFilterCount = Object.values(filters).filter(Boolean).length;
    const modalOpen = step !== "closed";

    // Tab stays in the dialog, Esc closes it, the page and nav behind it are inert, and focus goes back to the
    // "Add transaction" button that opened it
    useDialog(dialogRef, modalOpen, closeModal, addButtonRef);

    // stop the page behind the modal from scrolling
    useEffect(() => {
        if (!modalOpen) return;
        const previous = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        return () => {
            document.body.style.overflow = previous;
        };
    }, [modalOpen]);

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
        content = <TransactionList transactions={transactions} onChanged={reload}/>;
    }

    return (
        <div className="app-page">
            {/* made inert by useDialog while the add dialog is open */}
            <div className="transactions-page-content">
            <header>
                <h1 className="page-headers">Transactions</h1>
                <p className="page-subtitle">Every buy and sell you've logged.</p>
            </header>

            <div className="transactions-layout">
                <section className={`transactions-list-section${loading ? " is-refreshing" : ""}`}>
                    {content}
                </section>

                <aside className="transactions-sidebar">
                    <button className="btn btn-primary transaction-button-add" ref={addButtonRef}
                            onClick={() => setStep("search")}>
                        <span aria-hidden="true">+</span> Add transaction
                    </button>

                    <div className={`filter-add-section${filtersOpen ? " open" : ""}`}>
                        <div className="filter-heading">
                            <h2 className="filter-title">
                                <button className="filter-toggle" onClick={() => setFiltersOpen(!filtersOpen)}
                                        aria-expanded={filtersOpen}>
                                    Filters{activeFilterCount > 0 && <span className="filter-count">{activeFilterCount}</span>}
                                    <span className="filter-chevron" aria-hidden="true">▾</span>
                                </button>
                            </h2>
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
            </div>

            {step !== "closed" && (
                <div className="transaction-create-overlay" onMouseDown={(e) => e.target === e.currentTarget && closeModal()}>
                    <div className="transaction-create-box" role="dialog" aria-modal="true" aria-labelledby="add-transaction-title"
                         ref={dialogRef} tabIndex={-1}>
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
