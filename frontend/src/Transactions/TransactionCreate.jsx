import {useEffect, useState} from "react";
import {createTransaction, getHoldings} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatMoney, formatQuantity, priceInputValue} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import HoldingsChart from "../Holdings/HoldingsChart.jsx";
import TradeFields from "./TradeFields.jsx";
import {createPayload, isFutureInput, ledgerErrorMessage, toLocalInputValue} from "./tradeForm.js";

import "../css/Holdings.css";

function TransactionCreate({onClose, onCreated, data}) {
    const {currency} = useUser();
    // the date starts at "now"; it's only sent if the user changes it (see createPayload)
    const [initialDate] = useState(() => toLocalInputValue(new Date()));
    const [form, setForm] = useState({
        symbol: data.symbol,
        api_id: data.api_id,
        asset_type: data.type,
        quantity: "",
        // start from the current market price, the user can change it to what they actually paid
        price_of_one: priceInputValue(data.price),
        action: "BUY",
        created_at: initialDate,
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

    const setField = (name, value) => {
        setError(null);
        setForm((prev) => ({...prev, [name]: value}));
    };

    const quantityValid = Number(form.quantity) > 0;
    const priceValid = Number(form.price_of_one) > 0;
    const dateInFuture = isFutureInput(form.created_at);
    const backdated = Boolean(form.created_at) && form.created_at !== initialDate;

    const total = Number(form.quantity) * Number(form.price_of_one);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setError(null);

        try {
            await createTransaction(createPayload(form, initialDate));
            showToast(`${form.action === "BUY" ? "Buy" : "Sell"} of ${data.symbol.toUpperCase()} saved`);
            onCreated();
        } catch (err) {
            setError(ledgerErrorMessage(err, {mode: "create", symbol: data.symbol, action: form.action, backdated}));
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
                <TradeFields form={form} onField={setField} assetType={data.type} currency={currency}/>

                {form.action === "SELL" && owned !== null && (
                    <p className="create-total">
                        You own <strong>{formatQuantity(owned)} {data.symbol.toUpperCase()}</strong>
                        {backdated && " today"}
                        {owned > 0 && (
                            <button type="button" className="inline-link sell-all"
                                    onClick={() => setField("quantity", String(owned))}>
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
                {dateInFuture && <p className="create-hint">The date can't be in the future.</p>}

                <div className="create-transaction-buttons">
                    <button className="btn" type="button" onClick={onClose}>Cancel</button>
                    <button className="btn btn-success" type="submit"
                            disabled={submitting || !quantityValid || !priceValid || dateInFuture}>
                        {submitting ? "Saving…" : `Save ${form.action === "BUY" ? "buy" : "sell"}`}
                    </button>
                </div>
            </form>
        </div>
    );
}

export default TransactionCreate
