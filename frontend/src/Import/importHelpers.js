// Pure helpers for the Import & export page (tested in test/import-helpers.test.js)

// Same limits as the backend (backend/services/imports.py): checked here first so a huge file isn't read or sent
export const MAX_FILE_BYTES = 2 * 1024 * 1024;

export const FORMAT_OPTIONS = [
    {value: "auto", label: "Auto-detect"},
    {value: "zenith", label: "Zenith template"},
    {value: "wealthsimple", label: "Wealthsimple"},
    {value: "questrade", label: "Questrade"},
];

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

// What "Import" sends: every ready row, plus the duplicates the user ticked (by line number)
export function rowsToImport(rows, includedLines) {
    return (rows ?? []).filter((row) => row.status === "ok" || (row.status === "duplicate" && includedLines.has(row.line)));
}

export function importButtonLabel(count) {
    return count > 0 ? `Import ${plural(count, "trade")}` : "Nothing to import";
}

export const STATUS_LABELS = {ok: "Ready", duplicate: "Duplicate", error: "Problem"};

// Rows that need a look: problems, duplicates and ready rows with a note (e.g. "add .TO for a TSX listing")
export function needsAttention(row) {
    return row.status !== "ok" || Boolean(row.message);
}

// Showing thousands of rows at once makes phones crawl: show the first `limit` of the chosen filter
export const ROW_DISPLAY_LIMIT = 300;

export function visibleRows(rows, filter = "all", limit = ROW_DISPLAY_LIMIT) {
    const matching = (rows ?? []).filter((row) => filter !== "attention" || needsAttention(row));
    return {rows: matching.slice(0, limit), hidden: Math.max(0, matching.length - limit), total: matching.length};
}

// The row's date as the person reads it. Broker files only have a day, saved at noon UTC, which is that same day
// across Canada, so only the date is shown.
export function rowDate(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString(undefined, {year: "numeric", month: "short", day: "numeric"});
}
