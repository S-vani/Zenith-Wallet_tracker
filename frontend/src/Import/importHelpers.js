// Pure helpers for the Import & export page (tested in test/import-helpers.test.js)

// Same limits as the backend (backend/services/imports.py): checked here first so a huge file isn't read or sent
export const MAX_FILE_BYTES = 2 * 1024 * 1024;

export const FORMAT_OPTIONS = [
    {value: "auto", label: "Auto-detect"},
    {value: "zenith", label: "Zenith template"},
    {value: "wealthsimple", label: "Wealthsimple"},
    {value: "questrade", label: "Questrade"},
];

// A format's name for people ("Wealthsimple").
export function formatLabel(value) {
    return FORMAT_OPTIONS.find((option) => option.value === value)?.label ?? String(value ?? "");
}

const SPREADSHEET = /\.(xlsx|xlsm|xls|numbers|ods)$/i;

// What's wrong with a picked file before reading it, or null. Questrade's own export is an Excel file, so say how
// to turn that into a CSV rather than letting the server fail to read it.
export function fileProblem(file) {
    if (!file) return "Choose a CSV file to import.";
    if (SPREADSHEET.test(file.name ?? "")) {
        return "This is a spreadsheet file. Open it and save it as CSV (File → Save As → CSV), then choose the .csv file.";
    }
    if (file.size === 0) return "This file is empty.";
    if (file.size > MAX_FILE_BYTES) {
        return "This file is larger than 2 MB. Split it into smaller files (e.g. one per year) and import them one at a time.";
    }
    return null;
}

// "1 trade", "3 trades".
export function plural(n, one, many = `${one}s`) {
    return `${Number(n).toLocaleString()} ${n === 1 ? one : many}`;
}

// "3 trades ready · 1 already in your trades · 2 with problems · 4 other activities skipped"
export function summaryText(summary) {
    if (!summary) return "";
    const parts = [`${plural(summary.ok ?? 0, "trade")} ready`];
    if (summary.duplicate) parts.push(`${summary.duplicate.toLocaleString()} already in your trades`);
    if (summary.error) parts.push(`${summary.error.toLocaleString()} with problems`);
    if (summary.skipped_non_trades) {
        parts.push(`${plural(summary.skipped_non_trades, "other activity", "other activities")} skipped (dividends, deposits, fees…)`);
    }
    return parts.join(" · ");
}

// Every row but a problem can be ticked or unticked. `toggled` holds the lines the user flipped from the default:
// ready rows start ticked (so a line in it is left out), duplicates start unticked (so a line in it goes in).
export function isIncluded(row, toggled) {
    if (row.status === "ok") return !toggled.has(row.line);
    if (row.status === "duplicate") return toggled.has(row.line);
    return false;
}

// What "Import" sends: the ready rows the user kept, plus the duplicates they ticked
export function rowsToImport(rows, toggled) {
    return (rows ?? []).filter((row) => isIncluded(row, toggled));
}

// Only what the server needs for each row (not the status or the message), to keep a 5,000-row import small.
// A duplicate that's sent was ticked on purpose: the server would skip it otherwise.
export function commitRows(rows) {
    return rows.map((row) => ({
        line: row.line,
        date: row.date,
        date_only: Boolean(row.date_only),
        action: row.action,
        asset_type: row.asset_type,
        symbol: row.symbol,
        quantity: row.quantity,
        price: row.price,
        currency: row.currency,
        account_type: row.account_type,
        coin_id: row.coin_id,
        ...(row.status === "duplicate" ? {include_duplicate: true} : {}),
    }));
}

// A random id for one import (UUID v4), so the server can tell a retry from a second import
export function newImportId(cryptoApi = globalThis.crypto) {
    if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
    const bytes = new Uint8Array(16);
    if (typeof cryptoApi?.getRandomValues === "function") cryptoApi.getRandomValues(bytes);
    else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// "Imported 3 trades" plus how many the server found were already saved (e.g. after a retry)
export function importedText(result) {
    const text = `Imported ${plural(result?.imported ?? 0, "trade")}`;
    const skipped = result?.skipped_duplicates ?? 0;
    return skipped ? `${text} (${skipped.toLocaleString()} already in your trades were skipped)` : text;
}

// The import button's text for how many rows are selected.
export function importButtonLabel(count) {
    return count > 0 ? `Import ${plural(count, "trade")}` : "Nothing to import";
}

export const STATUS_LABELS = {ok: "Ready", duplicate: "Duplicate", error: "Problem"};

// Rows that need a look: problems, duplicates and ready rows with a note (e.g. "add .TO for a TSX listing")
export function needsAttention(row) {
    return row.status !== "ok" || Boolean(row.message);
}

// Showing thousands of rows at once makes phones crawl: show the first `limit` of the chosen filter
const ROW_DISPLAY_LIMIT = 300;

// The rows to show for a filter, at most `limit` of them, and how many were left out.
export function visibleRows(rows, filter = "all", limit = ROW_DISPLAY_LIMIT) {
    const matching = (rows ?? []).filter((row) => filter !== "attention" || needsAttention(row));
    return {rows: matching.slice(0, limit), hidden: Math.max(0, matching.length - limit), total: matching.length};
}

// The row's date as the person reads it (only the date is shown). Broker files only have a day, saved at the end of
// the trading day in UTC (21:00): that row shows its day as written in the file, whatever the phone's time zone.
export function rowDate(iso, dateOnly = false) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric", ...(dateOnly ? {timeZone: "UTC"} : {}),
    });
}
