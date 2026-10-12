import {useState} from "react";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPrice, formatQuantity, formatSignedMoney} from "../utils/format.js";

function TransactionItem({transaction, index}) {
    const [expanded, setExpanded] = useState(false);
    const {currency} = useUser();

    const created = new Date(transaction.created_at);
    const total = transaction.price_of_one * transaction.quantity;
    const unit = transaction.asset_type === "stock"
        ? (transaction.quantity === 1 ? "share" : "shares")
        : transaction.symbol.toUpperCase();
    const isBuy = transaction.action === "BUY";

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
                        <span className="transaction-date">
                            {created.toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"})}
                        </span>
                    </div>
                </div>

                <div className="transaction-right">
                    <span className="price-paid">
                        {formatMoney(total, currency)}
                    </span>

                    <span className="expand-icon" aria-hidden="true">▾</span>
                </div>
            </button>

            {expanded && (
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

                    <div className="transaction-id">ID {transaction.id}</div>
                </div>
            )}
        </div>
    )
}

export default TransactionItem
