import {accountLabel} from "../utils/accounts.js";

export const ACTION_LABELS = {BUY: "Buy", SELL: "Sell"};
export const KIND_LABELS = {stock: "Stocks", crypto: "Crypto"};

// What a pill / chip says for a group's value.
export function labelFor(group, value) {
    if (group === "actions") return ACTION_LABELS[value] ?? value;
    if (group === "kinds") return KIND_LABELS[value] ?? value;
    return value === "UNSET" ? "No account" : accountLabel(value);
}

