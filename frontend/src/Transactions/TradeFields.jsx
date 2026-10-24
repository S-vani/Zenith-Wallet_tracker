import {parseDecimalInput, toLocalInputValue} from "./tradeForm.js";
import {ACCOUNT_TYPES} from "../utils/accounts.js";

// typed but not a number above 0 (an empty field isn't flagged; Save just stays disabled)
const invalid = (text) => String(text ?? "").trim() !== "" && !(parseDecimalInput(text) > 0);

// Buy/sell, quantity, price, date and account fields, shared by the add form and the edit form of a trade
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

            {/* text + decimal keypad instead of type="number": WebKit drops "1,5" from a number field, which left
                Save disabled with no hint for anyone whose phone uses a decimal comma (see parseDecimalInput) */}
            <div className="quantity-price-buy">
                <label className="create-field">
                    <span>Quantity</span>
                    <input className="create-transaction-input" name="quantity" type="text"
                           inputMode="decimal" pattern="[0-9]*[.,]?[0-9]*" autoComplete="off" spellCheck={false}
                           required placeholder="0" value={form.quantity}
                           aria-invalid={invalid(form.quantity)}
                           onChange={(e) => onField("quantity", e.target.value)}/>
                </label>
                <label className="create-field">
                    <span>Price per {assetType === "stock" ? "share" : "coin"}{currency ? ` (${currency})` : ""}</span>
                    <input className="create-transaction-input" name="price_of_one" type="text"
                           inputMode="decimal" pattern="[0-9]*[.,]?[0-9]*" autoComplete="off" spellCheck={false}
                           required placeholder="0.00" value={form.price_of_one}
                           aria-invalid={invalid(form.price_of_one)}
                           onChange={(e) => onField("price_of_one", e.target.value)}/>
                </label>
            </div>

            {/* date and account share a row where there's room and wrap on small phones, so the optional account
                adds as little as possible to an already long sheet */}
            <div className="trade-date-account">
                <label className="create-field trade-date-field">
                    <span>Date &amp; time</span>
                    <input className="create-transaction-input trade-date-input" name="created_at"
                           type="datetime-local" max={maxDate} value={form.created_at}
                           onChange={(e) => onField("created_at", e.target.value)}/>
                </label>
                <label className="create-field trade-account-field">
                    <span>Account</span>
                    <select className="filter-select" name="account_type" value={form.account_type ?? ""}
                            onChange={(e) => onField("account_type", e.target.value)}>
                        <option value="">Not set</option>
                        {ACCOUNT_TYPES.map(({value, label}) => (
                            <option key={value} value={value}>{label}</option>
                        ))}
                    </select>
                </label>
            </div>
        </>
    );
}

export default TradeFields;
