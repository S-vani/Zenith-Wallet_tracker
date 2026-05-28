import {useState} from "react";

function TransactionItem({transaction, index}) {
    const [expanded, setExpanded] = useState(false);
    return (
        <div className="transaction-item-wrapper">
            <div className="transaction-item" style={{animationDelay: `${index * 0.1}s`}}
                 onClick={() => setExpanded(!expanded)}>
                <div className="transaction-left">
                    <p className="symbol">
                        {transaction.symbol}
                    </p>
                    <div className="asset-action">
                        <span>{transaction.asset_type.toUpperCase()}</span>

                        <span>{transaction.action}</span>
                    </div>
                </div>

                <div className="transaction-right">

                    <span className="price-paid">
                        $
                        {(transaction.price_of_one * transaction.quantity).toFixed(2)} CAD
                    </span>

                    <span>
                        {expanded ? "▲" : "▼"}
                    </span>

                </div>

            </div>
            {expanded && (
                <div className="transaction-expanded">

                    {/* TOP INFO */}
                    <div className="transaction-row">
                        <strong>Transaction ID:</strong>
                        <span>{transaction.id}</span>
                    </div>

                    <div className="transaction-row filled">
                        <strong>Filled:</strong>
                        <div className="value-stack">
                            <span>
                                {new Date(transaction.created_at).toLocaleDateString(
                                    "en-CA",
                                    {
                                        month: "short",
                                        day: "2-digit",
                                        year: "numeric",
                                        timeZone: "UTC",
                                    }
                                )}
                            </span>

                            <span>
                                {new Date(transaction.created_at).toLocaleTimeString(
                                    "en-CA",
                                    {
                                        hour: "2-digit",
                                        minute: "2-digit",
                                        timeZone: "UTC",
                                        timeZoneName: "short",
                                    }
                                )}
                            </span>
                        </div>
                    </div>

                    <div className="transaction-row">
                        <strong>User ID:</strong>
                        <span>{transaction.user_id}</span>
                    </div>

                    <div className="divider"/>

                    {/* MIDDLE INFO */}
                    <div className="transaction-row">
                        <strong>Action:</strong>
                        <span>{transaction.action}</span>
                    </div>

                    <div className="transaction-row">
                        <strong>Price:</strong>
                        <span>${transaction.price_of_one} CAD</span>
                    </div>

                    <div className="transaction-row">
                        <strong>Quantity:</strong>
                        <span>{transaction.quantity} Shares</span>
                    </div>

                    <div className="transaction-row">
                        <strong>Purchased:</strong>
                        <span>
                            {transaction.quantity} Shares × ${transaction.price_of_one} CAD
                        </span>
                    </div>

                    <div className="divider"/>

                    {/* BOTTOM INFO */}
                    <div className="transaction-row">
                        <strong>Total Cost:</strong>
                        <span>
                            ${(transaction.quantity * transaction.price_of_one).toFixed(2)} CAD
                        </span>
                    </div>

                    {transaction.action === "SELL" && (
                        <div className="transaction-row">
                            <strong>Profit:</strong>
                            <span>${transaction.profit}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default TransactionItem
