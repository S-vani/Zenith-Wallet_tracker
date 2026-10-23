import {useEffect, useRef, useState} from "react";
import {deleteTransaction} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPrice, formatQuantity, formatSignedMoney} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import TransactionEdit from "./TransactionEdit.jsx";
import {ledgerErrorMessage} from "./tradeForm.js";

function TransactionItem({transaction, index, onChanged}) {
    const [expanded, setExpanded] = useState(false);
    const [mode, setMode] = useState("view"); // "view" | "edit" | "delete" (asking to confirm)
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState(null);
    const {currency} = useUser();
    const editButtonRef = useRef(null);
    const leftMode = useRef(false); // back from edit/delete: put focus back on the Edit button, not the page top

    useEffect(() => {
        if (mode === "view" && leftMode.current) {
            leftMode.current = false;
            editButtonRef.current?.focus();
        }
    }, [mode]);

    const created = new Date(transaction.created_at);
    const total = transaction.price_of_one * transaction.quantity;
    const unit = transaction.asset_type === "stock"
        ? (transaction.quantity === 1 ? "share" : "shares")
        : transaction.symbol.toUpperCase();
    const isBuy = transaction.action === "BUY";
    const shortDate = created.toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"});

    const showMode = (next) => {
        setDeleteError(null);
        leftMode.current = next === "view";
        setMode(next);
    };

    const handleDelete = async () => {
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteTransaction(transaction.id);
            showToast(`${isBuy ? "Buy" : "Sell"} of ${transaction.symbol.toUpperCase()} deleted`);
            onChanged();
        } catch (err) {
            setDeleteError(ledgerErrorMessage(err, {mode: "delete", symbol: transaction.symbol}));
            setDeleting(false);
        }
    };

    return (
        <div className={`transaction-item-wrapper${expanded ? " open" : ""}`}
             style={{animationDelay: `${Math.min(index, 15) * 40}ms`}}>
            <button className="transaction-item" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
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
                        <span>{formatPrice(transaction.price_of_one, currency)}</span>
                    </div>

                    <div className="divider"/>

                    <div className="transaction-row total">
                        <span>{isBuy ? "Total cost" : "Total proceeds"}</span>
                        <span>{formatMoney(total, currency)}</span>
                    </div>

                    {!isBuy && (
                        <div className="transaction-row total">
                            <span>Realized profit</span>
                            <span className={changeClass(transaction.profit)}>
                                {formatSignedMoney(transaction.profit, currency)}
                            </span>
                        </div>
                    )}

                    {mode === "delete" ? (
                        <div className="transaction-delete-confirm" role="group"
                             aria-label={`Delete this ${isBuy ? "buy" : "sell"}?`}>
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
                                <button className="btn transaction-delete-submit" onClick={handleDelete}
                                        disabled={deleting}>
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
