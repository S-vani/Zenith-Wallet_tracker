import {useEffect, useState} from "react";
import {createTransaction, getHoldings} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatMoney, formatQuantity, priceInputValue} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import HoldingsChart from "../Holdings/HoldingsChart.jsx";

import "../css/Holdings.css";

function TransactionCreate({onClose, onCreated, data}) {
    const {currency} = useUser();
    const [form, setForm] = useState({
        symbol: data.symbol,
        api_id: data.api_id,
        asset_type: data.type,
        quantity: "",
        // start from the current market price, the user can change it to what they actually paid
        price_of_one: priceInputValue(data.price),
        action: "BUY",
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [owned, setOwned] = useState(null);

    // how much of this asset the user holds, shown when selling
    useEffect(() => {
        getHoldings()
            .then((holdings) => {
                const match = holdings.find((h) => h.symbol.toLowerCase() === data.api_id.toLowerCase() && h.type === data.type);
                setOwned(match ? match.quantity : 0);
            })
            .catch(() => null);
    }, [data.api_id, data.type]);

    const handleChange = (e) => {
        setError(null);
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    }

    const quantityValid = Number(form.quantity) > 0;
    const priceValid = Number(form.price_of_one) > 0;

    const total = Number(form.quantity) * Number(form.price_of_one);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setError(null);

        try {
            await createTransaction({
                ...form,
                quantity: Number(form.quantity),
                price_of_one: Number(form.price_of_one)
            });
            showToast(`${form.action === "BUY" ? "Buy" : "Sell"} of ${data.symbol.toUpperCase()} saved`);
            onCreated();
        } catch (err) {
            setError(err.message === "Insufficient holdings"
                ? `You can't sell more ${data.symbol.toUpperCase()} than you own.`
                : err.message);
            setSubmitting(false);
        }
    };

    return (
        <div className="transaction-create-wrapper">
            {form.action === "BUY" && (
                <div className="create-chart">
                    <span className="create-chart-label">{data.symbol.toUpperCase()} price</span>
                    <HoldingsChart symbol={data.api_id} type={data.type} initialRange="1D" compact/>
                </div>
            )}

            <h3>Transaction details</h3>

            <form className="create-transaction-form" autoComplete="off" onSubmit={handleSubmit}>
                <div className="segmented" role="group" aria-label="Buy or sell">
                    {["BUY", "SELL"].map((action) => (
                        <button
                            key={action}
                            type="button"
                            className={form.action === action ? `active ${action.toLowerCase()}` : ""}
                            aria-pressed={form.action === action}
                            onClick={() => {
                                setError(null);
                                setForm({...form, action});
                            }}
                        >
                            {action === "BUY" ? "Buy" : "Sell"}
                        </button>
                    ))}
                </div>

                <div className="quantity-price-buy">
                    <label className="create-field">
                        <span>Quantity</span>
                        <input className="create-transaction-input" name="quantity" type="number"
                               inputMode="decimal" step="any" min="0" required
                               placeholder="0" value={form.quantity} onChange={handleChange}/>
                    </label>
                    <label className="create-field">
                        <span>Price per {data.type === "stock" ? "share" : "coin"} ({currency})</span>
                        <input className="create-transaction-input" name="price_of_one" type="number"
                               inputMode="decimal" step="any" min="0" required
                               placeholder="0.00" value={form.price_of_one} onChange={handleChange}/>
                    </label>
                </div>

                {form.action === "SELL" && owned !== null && (
                    <p className="create-total">
                        You own <strong>{formatQuantity(owned)} {data.symbol.toUpperCase()}</strong>
                        {owned > 0 && (
                            <button type="button" className="inline-link sell-all"
                                    onClick={() => {
                                        setError(null);
                                        setForm({...form, quantity: String(owned)});
                                    }}>
                                Sell all
                            </button>
                        )}
                    </p>
                )}

                {total > 0 && (
                    <p className="create-total">
                        {form.action === "BUY" ? "Total cost" : "Total proceeds"}: <strong>{formatMoney(total, currency)}</strong>
                    </p>
                )}

                {error && <p className="alert-error" role="alert">{error}</p>}

                {(form.quantity !== "" && !quantityValid) || (form.price_of_one !== "" && !priceValid) ? (
                    <p className="create-hint">Quantity and price must both be greater than 0.</p>
                ) : null}

                <div className="create-transaction-buttons">
                    <button className="btn" type="button" onClick={onClose}>Cancel</button>
                    <button className="btn btn-success" type="submit"
                            disabled={submitting || !quantityValid || !priceValid}>
                        {submitting ? "Saving…" : `Save ${form.action === "BUY" ? "buy" : "sell"}`}
                    </button>
                </div>
            </form>
        </div>
    );
}

export default TransactionCreate
