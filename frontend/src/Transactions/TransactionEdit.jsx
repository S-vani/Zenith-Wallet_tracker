import {useEffect, useRef, useState} from "react";
import {updateTransaction} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatMoney, priceInputValue} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import TradeFields from "./TradeFields.jsx";
import {
    amountHint, isFutureInput, ledgerErrorMessage, parseDecimalInput, quantityInputValue, toLocalInputValue,
    updatePayload,
} from "./tradeForm.js";

// Inline form inside an expanded trade: same fields as the add form, starting from the trade's values
function TransactionEdit({transaction, onCancel, onSaved}) {
    const {currency} = useUser();
    const [initial] = useState(() => ({
        action: transaction.action,
        quantity: quantityInputValue(transaction.quantity), // never "1e-7", which the field can't take back
        price_of_one: priceInputValue(transaction.price_of_one),
        created_at: toLocalInputValue(transaction.created_at),
    }));
    const [form, setForm] = useState(initial);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const formRef = useRef(null);

    // the Edit button that opened this is gone, so start keyboard focus on the first field
    useEffect(() => {
        formRef.current?.querySelector("input")?.focus();
    }, []);

    const setField = (name, value) => {
        setError(null);
        setForm((prev) => ({...prev, [name]: value}));
    };

    const changes = updatePayload(initial, form);
    const quantity = parseDecimalInput(form.quantity); // "1,5" or "1.5", same as the add form
    const price = parseDecimalInput(form.price_of_one);
    const quantityValid = quantity > 0;
    const priceValid = price > 0;
    const hint = amountHint(form.quantity, form.price_of_one);
    const dateInFuture = isFutureInput(form.created_at);
    const total = quantity * price; // NaN (not shown) while either is invalid
    const symbol = transaction.symbol.toUpperCase();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            await updateTransaction(transaction.id, changes);
            showToast(`${symbol} trade updated`);
            onSaved();
        } catch (err) {
            setError(ledgerErrorMessage(err, {mode: "edit", symbol}));
            setSaving(false);
        }
    };

    return (
        <form ref={formRef} className="create-transaction-form transaction-edit-form" autoComplete="off"
              onSubmit={handleSubmit} aria-label={`Edit ${symbol} trade`}>
            <TradeFields form={form} onField={setField} assetType={transaction.asset_type} currency={currency}/>

            {total > 0 && (
                <p className="create-total">
                    {form.action === "BUY" ? "Total cost" : "Total proceeds"}: <strong>{formatMoney(total, currency)}</strong>
                </p>
            )}

            {error && <p className="alert-error" role="alert">{error}</p>}

            {hint && <p className="create-hint">{hint}</p>}
            {dateInFuture && <p className="create-hint">The date can't be in the future.</p>}

            <div className="create-transaction-buttons">
                <button className="btn" type="button" onClick={onCancel} disabled={saving}>Cancel</button>
                <button className="btn btn-success" type="submit"
                        disabled={saving || !quantityValid || !priceValid || dateInFuture
                            || Object.keys(changes).length === 0}>
                    {saving ? "Saving…" : "Save changes"}
                </button>
            </div>
        </form>
    );
}

export default TransactionEdit;
