import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {Link, useLocation, useSearchParams} from "react-router-dom";
import {getTransactions} from "../services/api";
import useRefreshKey from "../native/useRefreshKey.js";
import TransactionList from "../Transactions/TransactionList";
import TransactionCreate from "../Transactions/TransactionCreate.jsx"
import FilterBar from "../Transactions/FilterBar.jsx";
import {labelFor} from "../Transactions/filterLabels.js";
import {applyFilters, bestRelaxation, EMPTY_FILTERS, filtersFromSearch, filtersToSearch} from "../Transactions/filterModel.js";
import {DEFAULT_TRANSACTION_SORT, sortTransactions, TRANSACTION_SORTS} from "../Transactions/transactionSort.js";
import {ACCOUNT_TYPES} from "../utils/accounts.js";
import {useUser} from "../context/UserContext.jsx";
import TransactionSymbolSearch from "../Transactions/TransactionSymbolSearch.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import useDialog from "../Transactions/useDialog.js";
import useSheetDrag from "../native/useSheetDrag.js";

import '../css/Transaction.css'
import '../css/Filters.css'

const ACCOUNT_VALUES = ACCOUNT_TYPES.map((a) => a.value);

// Every trade, with filters, sorting and the add-trade dialog.
function TransactionsPage() {
    usePageTitle("Transactions");

    const [transactions, setTransactions] = useState([]);
    const {currency} = useUser();
    // the filters live in the address (?action=BUY&acct=TFSA...), so Back, reloads and shared links restore them
    const [params, setParams] = useSearchParams();
    const {filters, sort: urlSort} = useMemo(() => filtersFromSearch(params.toString(), ACCOUNT_VALUES), [params]);
    const sort = TRANSACTION_SORTS.some((o) => o.value === urlSort) ? urlSort : DEFAULT_TRANSACTION_SORT;
    const setView = useCallback((nextFilters, nextSort) => {
        setParams(filtersToSearch(nextFilters, nextSort), {replace: true});
    }, [setParams]);
    const changeFilters = useCallback((next) => setView(next, sort), [setView, sort]);
    const changeSort = useCallback((next) => setView(filters, next), [setView, filters]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [step, setStep] = useState("closed");
    const [symbolData, setSymbolData] = useState(null);
    const [scan, setScan] = useState(null); // {id, prefill, notes} when the trade was read from a screenshot
    const [reloadKey, setReloadKey] = useState(0);
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app
    const dialogRef = useRef(null);
    const addButtonRef = useRef(null);
    const headingRef = useRef(null);
    const listSectionRef = useRef(null);
    const focusAfterDelete = useRef(null); // position of a just-deleted trade, until the reloaded list is shown
    const [searchText, setSearchText] = useState(""); // typed in the dialog's symbol search
    const [confirmDiscard, setConfirmDiscard] = useState(false);
    const [justAdded, setJustAdded] = useState(null); // the trade just saved: its row glows once in the list
    const focusBeforeDiscard = useRef(null);

    // App only: the "Add trade" Home Screen quick action or Siri shortcut opens this page with {openAdd: true}.
    // Handled once per navigation (its location key), also when the page was already open.
    const location = useLocation();
    const [openedFor, setOpenedFor] = useState(null);
    if (location.state?.openAdd && openedFor !== location.key) {
        setOpenedFor(location.key);
        setStep("search");
    }

    // App only: the navigation bar's "+" (native/NativeTitleBar.jsx) opens the add form
    useEffect(() => {
        const open = () => setStep("search");
        window.addEventListener("app:add-trade", open);
        return () => window.removeEventListener("app:add-trade", open);
    }, []);

    useEffect(() => {
        let ignore = false;

        // every trade, once: the filters work on this list in the browser (Transactions/filterModel.js)
        getTransactions({})
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
    }, [reloadKey, refreshKey]);

    const reload = () => {
        setLoading(true);
        setReloadKey((k) => k + 1);
    };

    const clearFilters = () => changeFilters(EMPTY_FILTERS);

    // what is shown: the filters applied, then the sort
    const shown = useMemo(() => sortTransactions(applyFilters(transactions, filters), sort), [transactions, filters, sort]);
    const relax = useMemo(() => (shown.length === 0 ? bestRelaxation(transactions, filters, labelFor) : null),
        [shown, transactions, filters]);

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
        setScan(null);
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

    const modalOpen = step !== "closed";

    // Tab stays in the dialog, Esc asks to close it, the page and nav behind it are inert, and focus goes back to
    // the "Add transaction" button that opened it
    useDialog(dialogRef, modalOpen, requestClose, addButtonRef);
    useSheetDrag(dialogRef, modalOpen, requestClose); // app only

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
    } else if (shown.length === 0 && transactions.length > 0) {
        content = (
            <div className="state-message">
                <strong>No trades match</strong>
                {relax && (
                    <span>Removing “{relax.pill.label}” would show {relax.count} {relax.count === 1 ? "trade" : "trades"}.</span>
                )}
                <div className="state-actions">
                    {relax && <button className="btn btn-primary" onClick={() => changeFilters(relax.pill.off(filters))}>
                        Remove “{relax.pill.label}”
                    </button>}
                    <button className="btn" onClick={clearFilters}>Clear all filters</button>
                </div>
            </div>
        );
    } else if (transactions.length === 0) {
        content = (
            <div className="state-message">
                <strong>No transactions yet</strong>
                Log your first buy to start tracking your portfolio.
                <button className="btn btn-primary" onClick={() => setStep("search")}>Add transaction</button>
            </div>
        );
    } else {
        content = <TransactionList transactions={shown} onChanged={reload} onDeleted={deleted}
                                   justAdded={justAdded}/>;
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
                    <Link to="/reports">Tax report</Link>
                </nav>
            </header>

            <div className="transactions-layout">
                <div className="transactions-toolbar">
                    <button className="btn btn-primary transaction-button-add" ref={addButtonRef}
                            onClick={() => setStep("search")}>
                        <span aria-hidden="true">+</span> Add transaction
                    </button>
                </div>

                {transactions.length > 0 && (
                    <FilterBar trades={transactions} shown={shown} filters={filters} onChange={changeFilters}
                               sort={sort} onSort={changeSort} currency={currency}/>
                )}

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
                            onSub={(data, scanned = null) => {
                                setSymbolData(data);
                                setScan(scanned);
                                setStep("create");
                            }}
                        />

                        {/* a new scan restarts the form with its values, even for the same asset */}
                        {step === "create" && symbolData && (
                            <TransactionCreate
                                key={scan ? `${symbolData.api_id}:scan${scan.id}` : symbolData.api_id}
                                data={symbolData}
                                prefill={scan?.prefill}
                                scanNotes={scan?.notes}
                                onClose={closeModal}
                                onCreated={(id) => {
                                    setJustAdded(id ?? null);
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
