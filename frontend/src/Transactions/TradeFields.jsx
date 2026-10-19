import {toLocalInputValue} from "./tradeForm.js";

// Buy/sell, quantity, price and date fields, shared by the add form and the edit form of a trade
function TradeFields({form, onField, assetType, currency}) {
    // native picker (a wheel on phones); max blocks future dates where browsers support it, the form checks too
    const maxDate = toLocalInputValue(new Date());

    return (
        <>
            <div className="segmented" role="group" aria-label="Buy or sell">
                {["BUY", "SELL"].map((action) => (
                    <button
                        key={action}
                        type="button"
                        className={form.action === action ? `active ${action.toLowerCase()}` : ""}
                        aria-pressed={form.action === action}
                        onClick={() => onField("action", action)}
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
                           placeholder="0" value={form.quantity}
                           onChange={(e) => onField("quantity", e.target.value)}/>
                </label>
                <label className="create-field">
                    <span>Price per {assetType === "stock" ? "share" : "coin"} ({currency})</span>
                    <input className="create-transaction-input" name="price_of_one" type="number"
                           inputMode="decimal" step="any" min="0" required
                           placeholder="0.00" value={form.price_of_one}
                           onChange={(e) => onField("price_of_one", e.target.value)}/>
                </label>
            </div>

            <label className="create-field">
                <span>Date &amp; time</span>
                <input className="create-transaction-input trade-date-input" name="created_at" type="datetime-local"
                       max={maxDate} value={form.created_at}
                       onChange={(e) => onField("created_at", e.target.value)}/>
            </label>
        </>
    );
}

export default TradeFields;
