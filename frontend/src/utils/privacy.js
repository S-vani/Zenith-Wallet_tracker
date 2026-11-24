// Privacy mode: the eye on the dashboard's value card hides every amount of the person's own money (portfolio value,
// returns, holdings, trades, allocation, the X-Ray's total) behind a blur, for checking the app in public. Market
// prices stay visible. Saved in this browser / phone; <html class="amounts-hidden"> does the hiding (Global.css).
const KEY = "hideAmounts";

// Whether amounts are hidden right now.
export function amountsHidden() {
    try {
        return localStorage.getItem(KEY) === "yes";
    } catch {
        return false;
    }
}

// Puts the saved choice on the page (at startup).
export function applyAmountsHidden() {
    document.documentElement.classList.toggle("amounts-hidden", amountsHidden());
}

// Hides or shows amounts, saves the choice, and returns the new state.
export function toggleAmountsHidden() {
    const hidden = !amountsHidden();
    try {
        if (hidden) localStorage.setItem(KEY, "yes");
        else localStorage.removeItem(KEY);
    } catch {
        // still applied for now
    }
    document.documentElement.classList.toggle("amounts-hidden", hidden);
    return hidden;
}
