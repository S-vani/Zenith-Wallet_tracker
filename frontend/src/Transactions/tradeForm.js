// Pure helpers shared by the add and edit trade forms (tested in test/tradeForm.test.js)

const pad = (n) => String(n).padStart(2, "0");

// A Date as the "YYYY-MM-DDTHH:MM" local time a datetime-local input shows
export function toLocalInputValue(date) {
    const d = new Date(date);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// A datetime-local value has no time zone and JS reads it as local time, so this is the user's local time in UTC
// (the same way the date filters send their start/end of day). The backend stores it as naive UTC.
export function localInputToIso(value) {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function isFutureInput(value, now = new Date()) {
    if (!value) return false;
    const d = new Date(value);
    return !Number.isNaN(d.getTime()) && d > now;
}

// Body for POST /transactions. The date is only sent when the user changed it, so an untouched form is dated
// "now" by the server at the moment it's saved.
export function createPayload(form, initialDate) {
    const changedDate = form.created_at && form.created_at !== initialDate;
    return {
        symbol: form.symbol,
        api_id: form.api_id,
        asset_type: form.asset_type,
        action: form.action,
        quantity: Number(form.quantity),
        price_of_one: Number(form.price_of_one),
        ...(changedDate ? {created_at: localInputToIso(form.created_at)} : {}),
    };
}

// Body for PUT /transactions/{id}: only what changed. Re-sending an unchanged price would convert an old trade's
// price at today's exchange rate, and re-sending the date would drop its seconds.
export function updatePayload(initial, form) {
    const changes = {};
    if (form.action !== initial.action) changes.action = form.action;
    if (form.quantity !== initial.quantity) changes.quantity = Number(form.quantity);
    if (form.price_of_one !== initial.price_of_one) changes.price_of_one = Number(form.price_of_one);
    if (form.created_at && form.created_at !== initial.created_at) {
        changes.created_at = localInputToIso(form.created_at);
    }
    return changes;
}

// The backend answers 409 when a save, edit or delete would make the history sell more than was owned at some
// point. Say what that means for the thing the user just tried.
export function ledgerErrorMessage(err, {mode, symbol = "", action = "BUY", backdated = false} = {}) {
    if (err?.status !== 409) return err?.message ?? "Something went wrong. Please try again.";
    const name = symbol.toUpperCase();

    if (mode === "delete") {
        return `This buy can't be deleted: a later sell of ${name} needs it. Delete or edit that sell first.`;
    }
    if (mode === "edit") {
        return `That change would leave your ${name} history selling more than you owned at the time. ` +
            "Check the quantity and date, and any sells after it.";
    }
    if (action === "SELL" && backdated) {
        return `You didn't own that much ${name} on that date (or it would leave a later sell short).`;
    }
    if (action === "SELL") return `You can't sell more ${name} than you own.`;
    return `Saving this would leave your ${name} history selling more than you owned at the time.`;
}
