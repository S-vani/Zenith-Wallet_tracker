import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {getTransactions} from "../services/api";
import useRefreshKey from "../native/useRefreshKey.js";
import TransactionList from "../Transactions/TransactionList";
import TransactionCreate from "../Transactions/TransactionCreate.jsx"
import TransactionFilter from "../Transactions/TransactionFilter.jsx"
import TransactionSymbolSearch from "../Transactions/TransactionSymbolSearch.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useDialog from "../Transactions/useDialog.js";

import '../css/Transaction.css'

const EMPTY_FILTERS = {symbol: "", action: "", account_type: "", start_date: "", end_date: ""};

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
    const filterToggleRef = useRef(null);
    const headingRef = useRef(null);
    const listSectionRef = useRef(null);
    const focusAfterDelete = useRef(null); // position of a just-deleted trade, until the reloaded list is shown
    const [searchText, setSearchText] = useState(""); // typed in the dialog's symbol search
    const [confirmDiscard, setConfirmDiscard] = useState(false);
    const focusBeforeDiscard = useRef(null);

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

    // the clicked "Clear" button disappears with the filters, so focus would fall to <body>
    const clearFilters = () => {
        changeFilters(EMPTY_FILTERS);
        filterToggleRef.current?.focus();
    };

    // after a delete, focus the trade that took its place (or the one before it, if it was last), else the heading
    const deleted = (index) => {
        focusAfterDelete.current = index;
        reload();
    };

    useEffect(() => {
        if (loading || focusAfterDelete.current === null) return;
        const rows = listSectionRef.current?.querySelectorAll(".transaction-item") ?? [];
        (rows[Math.min(focusAfterDelete.current, rows.length - 1)] ?? headingRef.current)?.focus();
        focusAfterDelete.current = null;
    }, [loading, transactions]);

    const closeModal = () => {
        setStep("closed");
        setSymbolData(null);
        setSearchText("");
        setConfirmDiscard(false);
    };

    const keepEditing = () => {
        setConfirmDiscard(false);
        const previous = focusBeforeDiscard.current;
        (previous?.isConnected && previous !== document.body ? previous : dialogRef.current)?.focus();
    };

    // A tap on the backdrop or Esc is easy to do by accident, so once a trade is started (an asset picked or
    // anything typed) ask before throwing it away. Close and Cancel are deliberate and still close straight away.
    const requestClose = () => {
        if (confirmDiscard) {
            keepEditing(); // Esc on the question means "keep editing"
        } else if (symbolData !== null || searchText.trim() !== "") {
            focusBeforeDiscard.current = document.activeElement;
            setConfirmDiscard(true);
        } else {
            closeModal();
        }
    };

    const hasFilters = Object.values(filters).some(Boolean);
    const activeFilterCount = Object.values(filters).filter(Boolean).length;
    const modalOpen = step !== "closed";

    // Tab stays in the dialog, Esc asks to close it, the page and nav behind it are inert, and focus goes back to
    // the "Add transaction" button that opened it
    useDialog(dialogRef, modalOpen, requestClose, addButtonRef);

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
        content = (
            <div className="alert-error alert-retry" role="alert">
                <span>{error}</span>
                <button type="button" className="btn" onClick={reload}>Try again</button>
            </div>
        );
    } else if (transactions.length === 0) {
        content = hasFilters ? (
            <div className="state-message">
                <strong>No transactions match these filters</strong>
                <button className="btn" onClick={clearFilters}>Clear filters</button>
            </div>
        ) : (
            <div className="state-message">
                <strong>No transactions yet</strong>
                Log your first buy to start tracking your portfolio.
                <button className="btn btn-primary" onClick={() => setStep("search")}>Add transaction</button>
            </div>
        );
    } else {
        content = <TransactionList transactions={transactions} onChanged={reload} onDeleted={deleted}/>;
    }

    return (
        <div className="app-page">
            {/* made inert by useDialog while the add dialog is open */}
            <div className="transactions-page-content">
            <header>
                {/* tabIndex -1: where focus lands after deleting the last trade */}
                <h1 className="page-headers" ref={headingRef} tabIndex={-1}>Transactions</h1>
                <p className="page-subtitle">Every buy and sell you've logged.</p>
                {/* the bulk tools live on their own pages; linked here because this is where trades are managed */}
                <nav className="page-links" aria-label="More for your trades">
                    <Link to="/import">Import &amp; export CSV</Link>
                    <Link to="/reports">Capital gains report</Link>
                </nav>
            </header>

            <div className="transactions-layout">
                {/* the sidebar comes first in the DOM because phones show it above the list, so Tab and screen
                    readers meet it in the order it's seen; on desktop the grid still puts it on the right */}
                <aside className="transactions-sidebar">
                    <button className="btn btn-primary transaction-button-add" ref={addButtonRef}
                            onClick={() => setStep("search")}>
                        <span aria-hidden="true">+</span> Add transaction
                    </button>

                    <div className={`filter-add-section${filtersOpen ? " open" : ""}`}>
                        <div className="filter-heading">
                            <h2 className="filter-title">
                                <button className="filter-toggle" ref={filterToggleRef}
                                        onClick={() => setFiltersOpen(!filtersOpen)} aria-expanded={filtersOpen}>
                                    Filters{activeFilterCount > 0 && <span className="filter-count">{activeFilterCount}</span>}
                                    <span className="filter-chevron" aria-hidden="true">▾</span>
                                </button>
                            </h2>
                            {hasFilters && (
                                <button className="filter-clear" onClick={clearFilters}>
                                    Clear all
                                </button>
                            )}
                        </div>
                        <TransactionFilter filters={filters} onFiltered={changeFilters}/>
                    </div>
                </aside>

                <section className={`transactions-list-section${loading ? " is-refreshing" : ""}`}
                         ref={listSectionRef}>
                    {content}
                </section>
            </div>
            </div>

            {step !== "closed" && (
                <div className="transaction-create-overlay"
                     onMouseDown={(e) => e.target === e.currentTarget && requestClose()}>
                    <div className="transaction-create-box" role="dialog" aria-modal="true" aria-labelledby="add-transaction-title"
                         ref={dialogRef} tabIndex={-1}>
                        {/* sticky, so the title, the close button and the discard question stay in view */}
                        <div className="modal-header">
                            <div className="modal-header-row">
                                <h2 id="add-transaction-title">Add transaction</h2>
                                <button className="transaction-create-close-button" onClick={closeModal}
                                        aria-label="Close">
                                    <img src="/assets/close.png" alt=""/>
                                </button>
                            </div>

                            {confirmDiscard && (
                                <div className="discard-confirm" role="group" aria-labelledby="discard-trade-title">
                                    <p id="discard-trade-title">Discard this trade?</p>
                                    <div className="discard-confirm-buttons">
                                        {/* focus starts on the safe choice */}
                                        <button type="button" className="btn" onClick={keepEditing} autoFocus>
                                            Keep editing
                                        </button>
                                        <button type="button" className="btn transaction-delete-submit"
                                                onClick={closeModal}>
                                            Discard
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>

                        <TransactionSymbolSearch
                            onQueryChange={setSearchText}
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
