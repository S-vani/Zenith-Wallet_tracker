import {useEffect, useRef, useState} from "react";
import {deleteTransaction} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatQuantity} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import TransactionEdit from "./TransactionEdit.jsx";
import {fullMoney, fullPrice, fullSignedMoney, ledgerErrorMessage} from "./tradeForm.js";

function TransactionItem({transaction, index, onChanged, onDeleted}) {
    const [expanded, setExpanded] = useState(false);
    const [mode, setMode] = useState("view"); // "view" | "edit" | "delete" (asking to confirm)
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState(null);
    const {currency} = useUser();
    const rowButtonRef = useRef(null);
    const editButtonRef = useRef(null);
    // back from edit/delete: where focus goes ("edit" button or the trade "row"), rather than the page top
    const returnFocus = useRef(null);

    useEffect(() => {
        if (mode === "view" && returnFocus.current) {
            (returnFocus.current === "row" ? rowButtonRef : editButtonRef).current?.focus();
            returnFocus.current = null;
        }
    }, [mode]);

    const created = new Date(transaction.created_at);
    const total = transaction.price_of_one * transaction.quantity;
    const unit = transaction.asset_type === "stock"
        ? (transaction.quantity === 1 ? "share" : "shares")
        : transaction.symbol.toUpperCase();
    const isBuy = transaction.action === "BUY";
    const shortDate = created.toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"});

    const showMode = (next, focusTarget = "edit") => {
        setDeleteError(null);
        returnFocus.current = next === "view" ? focusTarget : null;
        setMode(next);
    };

    const handleDelete = async () => {
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteTransaction(transaction.id);
            showToast(`${isBuy ? "Buy" : "Sell"} of ${transaction.symbol.toUpperCase()} deleted`);
            onDeleted(); // reloads the list and moves focus off this row, which is about to disappear
        } catch (err) {
            setDeleteError(ledgerErrorMessage(err, {mode: "delete", symbol: transaction.symbol}));
            setDeleting(false);
        }
    };

    return (
        <div className={`transaction-item-wrapper${expanded ? " open" : ""}`}
             style={{animationDelay: `${Math.min(index, 15) * 40}ms`}}>
            <button className="transaction-item" ref={rowButtonRef} onClick={() => setExpanded(!expanded)}
                    aria-expanded={expanded}>
                <div className="transaction-left">
                    <span className="transaction-symbol">
                        {transaction.symbol}
                    </span>
                    <div className="asset-action">
                        <span className={`action-badge ${isBuy ? "buy" : "sell"}`}>{isBuy ? "Buy" : "Sell"}</span>
                        <span>{transaction.asset_type}</span>
                        <span className="transaction-date">{shortDate}</span>
                    </div>
                </div>

                <div className="transaction-right">
                    <span className="price-paid">
                        {formatMoney(total, currency)}
                    </span>

                    <span className="expand-icon" aria-hidden="true">▾</span>
                </div>
            </button>

            {expanded && mode === "edit" && (
                <div className="transaction-expanded">
                    <TransactionEdit
                        transaction={transaction}
                        onCancel={() => showMode("view")}
                        onSaved={() => {
                            showMode("view");
                            onChanged();
                        }}
                    />
                </div>
            )}

            {expanded && mode !== "edit" && (
                <div className="transaction-expanded">
                    <div className="transaction-row">
                        <span>Filled</span>
                        <span>
                            {created.toLocaleString(undefined, {
                                month: "short",
                                day: "numeric",
                                year: "numeric",
                                hour: "numeric",
                                minute: "2-digit",
                                timeZoneName: "short",
                            })}
                        </span>
                    </div>

                    <div className="transaction-row">
                        <span>Quantity</span>
                        <span>{formatQuantity(transaction.quantity)} {unit}</span>
                    </div>

                    <div className="transaction-row">
                        <span>Price per {transaction.asset_type === "stock" ? "share" : "coin"}</span>
                        <span>{fullPrice(transaction.price_of_one, currency)}</span>
                    </div>

                    <div className="divider"/>

                    {/* exact amounts here (the row above may shorten huge ones to "CA$97.5T") */}
                    <div className="transaction-row total">
                        <span>{isBuy ? "Total cost" : "Total proceeds"}</span>
                        <span>{fullMoney(total, currency)}</span>
                    </div>

                    {!isBuy && (
                        <div className="transaction-row total">
                            <span>Realized profit</span>
                            <span className={changeClass(transaction.profit)}>
                                {fullSignedMoney(transaction.profit, currency)}
                            </span>
                        </div>
                    )}

                    {mode === "delete" ? (
                        // Esc = "Keep it", back on the trade's row (the list has no dialog of its own to close)
                        <div className="transaction-delete-confirm" role="group"
                             aria-label={`Delete this ${isBuy ? "buy" : "sell"}?`}
                             onKeyDown={(e) => {
                                 if (e.key !== "Escape" || deleting) return;
                                 e.stopPropagation();
                                 showMode("view", "row");
                             }}>
                            <p>
                                Delete this {isBuy ? "buy" : "sell"} of {formatQuantity(transaction.quantity)} {unit}
                                {" "}from {shortDate}? Your holdings and returns will be recalculated. This can't be
                                undone.
                            </p>
                            {deleteError && <p className="alert-error" role="alert">{deleteError}</p>}
                            <div className="transaction-actions">
                                {/* focus starts on the safe choice */}
                                <button className="btn" onClick={() => showMode("view")} disabled={deleting} autoFocus>
                                    Keep it
                                </button>
                                {/* after a blocked delete, trying again can't work until the later trade changes */}
                                <button className="btn transaction-delete-submit" onClick={handleDelete}
                                        disabled={deleting || Boolean(deleteError)}>
                                    {deleting ? "Deleting…" : "Delete trade"}
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="transaction-actions">
                            <button className="btn" ref={editButtonRef} onClick={() => showMode("edit")}>Edit</button>
                            <button className="btn transaction-delete-button" onClick={() => showMode("delete")}>
                                Delete…
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default TransactionItem
