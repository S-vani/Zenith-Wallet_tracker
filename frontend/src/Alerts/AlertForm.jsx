import {useState} from "react";
import {useNavigate} from "react-router-dom";
import {createAlert} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatPrice} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import {haptic} from "../native/haptics.js";
import {enablePush} from "../native/push.js";
import {parseDecimalInput} from "../Transactions/tradeForm.js";

const KINDS = [
    {value: "above", label: "Rises above"},
    {value: "below", label: "Falls below"},
    {value: "move", label: "Big move"},
];

// a starting target 10% above / below today's price, rounded to cents ("" when there's no price)
const suggested = (price, kind) => (Number(price) > 0
    ? String(Math.round(price * (kind === "below" ? 0.9 : 1.1) * 100) / 100) : "");

// "Set an alert" under an asset's price (Search detail): a price above / below, or a big daily move either way.
// The server checks it every few minutes and notifies in the app's inbox and, when allowed, on the phone.
function AlertForm({asset, onDone}) {
    const {currency} = useUser();
    const navigate = useNavigate();
    const [kind, setKind] = useState("above");
    const [price, setPrice] = useState(() => suggested(asset.price, "above"));
    const [move, setMove] = useState("5");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const value = parseDecimalInput(kind === "move" ? move : price);
    const valid = kind === "move" ? value >= 1 && value <= 50 : value > 0;

    const choose = (next) => {
        setKind(next);
        setError(null);
        if (next !== "move") setPrice(suggested(asset.price, next));
    };

    const save = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            await createAlert({api_id: asset.api_id, type: asset.type, coin_id: asset.coin_id ?? null, kind,
                threshold: value});
            haptic("success");
            const symbol = asset.symbol.toUpperCase();
            showToast(kind === "move" ? `Alert set: ${symbol} moving ${value}% in a day`
                : `Alert set: ${symbol} ${kind === "above" ? "above" : "below"} ${formatPrice(value, currency)}`);
            onDone();
            enablePush(navigate); // app only: iOS asks once whether Zenith may send notifications
        } catch (err) {
            setError(err.message);
            setSaving(false);
        }
    };

    return (
        <form className="alert-form" onSubmit={save}>
            <div className="segmented alert-kinds" role="radiogroup" aria-label="Alert me when the price">
                {KINDS.map(({value: v, label}) => (
                    <button key={v} type="button" role="radio" aria-checked={kind === v}
                            className={kind === v ? "active" : ""} onClick={() => choose(v)}>
                        {label}
                    </button>
                ))}
            </div>
            {kind === "move" ? (
                <label className="alert-field">
                    <span>Up or down by at least (%) in a day</span>
                    <input type="text" inputMode="decimal" value={move} onChange={(e) => setMove(e.target.value)}
                           aria-invalid={move !== "" && !valid}/>
                </label>
            ) : (
                <label className="alert-field">
                    <span>Price ({currency})</span>
                    <input type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)}
                           aria-invalid={price !== "" && !valid}/>
                </label>
            )}
            <p className="alert-hint">
                {kind === "move"
                    ? "Checked every few minutes, at most one notification a day."
                    : `Now ${formatPrice(asset.price, currency)}. You get one notification, then the alert turns off.`}
            </p>
            {error && <p className="alert-error" role="alert">{error}</p>}
            <div className="alert-form-actions">
                <button type="button" className="btn" onClick={onDone}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={!valid || saving}>
                    {saving ? "Saving…" : "Set alert"}
                </button>
            </div>
        </form>
    );
}

export default AlertForm;
