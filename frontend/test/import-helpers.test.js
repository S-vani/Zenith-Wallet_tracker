import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {
    FORMAT_OPTIONS,
    MAX_FILE_BYTES,
    fileProblem,
    formatLabel,
    importButtonLabel,
    needsAttention,
    rowDate,
    rowsToImport,
    summaryText,
    visibleRows,
} from "../src/Import/importHelpers.js";

describe("fileProblem", () => {
    it("accepts a normal CSV", () => {
        expect(fileProblem({name: "trades.csv", size: 1200})).toBeNull();
        expect(fileProblem({name: "trades.CSV", size: MAX_FILE_BYTES})).toBeNull();
    });

    it("explains what's wrong before anything is read or sent", () => {
        expect(fileProblem(null)).toMatch(/Choose a CSV/);
        expect(fileProblem({name: "a.csv", size: 0})).toMatch(/empty/);
        expect(fileProblem({name: "a.csv", size: MAX_FILE_BYTES + 1})).toMatch(/larger than 2 MB/);
        // Questrade's export is an Excel file
        expect(fileProblem({name: "Activities.xlsx", size: 5000})).toMatch(/save it as CSV/);
        expect(fileProblem({name: "old.xls", size: 5000})).toMatch(/save it as CSV/);
    });
});

describe("summaryText", () => {
    it("names only what's there", () => {
        expect(summaryText({ok: 3, duplicate: 0, error: 0, skipped_non_trades: 0})).toBe("3 trades ready");
        expect(summaryText({ok: 1, duplicate: 2, error: 1, skipped_non_trades: 1})).toBe(
            "1 trade ready · 2 already in your trades · 1 with problems · 1 other activity skipped (dividends, deposits, fees…)");
        expect(summaryText({ok: 1200, duplicate: 0, error: 0, skipped_non_trades: 4})).toBe(
            "1,200 trades ready · 4 other activities skipped (dividends, deposits, fees…)");
        expect(summaryText(null)).toBe("");
    });
});

const ROWS = [
    {line: 2, status: "ok", message: null},
    {line: 3, status: "duplicate", message: "Already in your trades"},
    {line: 4, status: "error", message: "Missing price"},
    {line: 5, status: "duplicate", message: "Already in your trades"},
    {line: 6, status: "ok", message: "No exchange in the file"},
];

describe("rowsToImport", () => {
    it("sends ready rows and only the duplicates that were ticked, never problems", () => {
        expect(rowsToImport(ROWS, new Set()).map((r) => r.line)).toEqual([2, 6]);
        expect(rowsToImport(ROWS, new Set([5, 4])).map((r) => r.line)).toEqual([2, 5, 6]);
        expect(rowsToImport(undefined, new Set())).toEqual([]);
    });

    it("labels the button with the count", () => {
        expect(importButtonLabel(0)).toBe("Nothing to import");
        expect(importButtonLabel(1)).toBe("Import 1 trade");
        expect(importButtonLabel(2500)).toBe("Import 2,500 trades");
    });
});

describe("visibleRows", () => {
    it("filters to rows that need a look", () => {
        expect(ROWS.filter(needsAttention).map((r) => r.line)).toEqual([3, 4, 5, 6]);
        expect(visibleRows(ROWS, "attention")).toMatchObject({hidden: 0, total: 4});
        expect(visibleRows(ROWS, "all").rows).toHaveLength(5);
    });

    it("caps how many rows are drawn", () => {
        const many = Array.from({length: 10}, (_, i) => ({line: i + 2, status: "ok"}));
        const shown = visibleRows(many, "all", 4);
        expect(shown.rows.map((r) => r.line)).toEqual([2, 3, 4, 5]);
        expect(shown).toMatchObject({hidden: 6, total: 10});
    });
});

describe("labels", () => {
    it("knows every format the backend accepts", () => {
        expect(FORMAT_OPTIONS.map((o) => o.value)).toEqual(["auto", "zenith", "wealthsimple", "questrade"]);
        expect(formatLabel("wealthsimple")).toBe("Wealthsimple");
        expect(formatLabel("zenith")).toBe("Zenith template");
    });

    it("shows a broker row's day (stored at noon UTC) as that same day in Canada", () => {
        expect(rowDate("2024-02-01T12:00:00+00:00")).toBe("Feb 1, 2024");
        expect(rowDate(null)).toBe("—");
        expect(rowDate("nope")).toBe("—");
    });
});

// api.js reads the backend url at import time, so import it fresh per test (same setup as api.test.js)
const BASE = "http://api.test";
let api;
let fetchMock;

describe("import api", () => {
    beforeEach(async () => {
        vi.resetModules();
        vi.stubEnv("VITE_BACKEND_URL", BASE);
        const store = new Map([["token", "abc"]]);
        vi.stubGlobal("localStorage", {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, String(v)),
            removeItem: (k) => store.delete(k),
        });
        vi.stubGlobal("window", {dispatchEvent: () => true});
        fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        api = await import("../src/services/api.js");
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.unstubAllEnvs();
    });

    it("previews with the chosen format and default account", async () => {
        fetchMock.mockResolvedValue({ok: true, status: 200, json: async () => ({rows: []})});
        await api.previewImport("a,b", "questrade", "TFSA");
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/import/preview`);
        expect(JSON.parse(options.body)).toEqual({csv: "a,b", format: "questrade", default_account_type: "TFSA"});
    });

    it("keeps the 409 so the page can explain nothing was saved", async () => {
        fetchMock.mockResolvedValue({
            ok: false, status: 409, json: async () => ({detail: "Nothing was imported: line 4 sells too much NVDA."}),
        });
        await expect(api.commitImport([{line: 4}])).rejects.toMatchObject({
            status: 409, message: "Nothing was imported: line 4 sells too much NVDA.",
        });
    });

    it("downloads the export as text with a dated file name", async () => {
        fetchMock.mockResolvedValue({ok: true, status: 200, text: async () => "date,action\r\n"});
        const file = await api.exportTradesCsv(new Date(Date.UTC(2026, 9, 24, 3)));
        expect(file).toEqual({filename: "zenith-trades-2026-10-24.csv", text: "date,action\r\n"});
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/export`);
        expect(options.headers.Authorization).toBe("Bearer abc");
    });

    it("signs out when the session is gone", async () => {
        fetchMock.mockResolvedValue({ok: false, status: 401, json: async () => ({})});
        await expect(api.getImportTemplate()).rejects.toThrow(/session has expired/);
        expect(localStorage.getItem("token")).toBeNull();
    });
});
