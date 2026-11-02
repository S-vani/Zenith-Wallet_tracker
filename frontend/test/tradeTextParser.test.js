import {describe, expect, it} from "vitest";
import {findDateTime, MAX_TRADES, parseTradeText} from "../src/Transactions/tradeTextParser.js";

// The rule parser behind "Scan a screenshot": lines of text read on the device (Apple Vision or Tesseract) in,
// trade fields for POST /transactions/scan/fields out. Fixtures are what OCR gives for real broker screens, noise
// included. The time zone is pinned to America/Toronto (test/setup.js).

const NOW = new Date("2026-11-01T15:30:00Z"); // Sunday Nov 1, 2026, 10:30 in Toronto

// A screen as rows, top to bottom, with coordinates like the readers give (0..1 of the image, top left origin).
// A row is a string (one line across) or [left, right] / [[text, x], ...] for parts side by side. `gap` spaces rows.
function screen(rows, {top = 0.08, gap = 0.045, height = 0.022} = {}) {
    const lines = [];
    rows.forEach((row, i) => {
        const y = top + i * gap;
        const parts = typeof row === "string" ? [[row, 0.05]]
            : row.map((part, k) => (Array.isArray(part) ? part : [part, k === 0 ? 0.05 : 0.6]));
        for (const [text, x] of parts) lines.push({text, x, y, w: Math.min(0.9 - x, text.length * 0.02), h: height});
    });
    return lines;
}

// the phone's status bar and a tab bar, around every screen
const STATUS_BAR = [
    {text: "9:41", x: 0.06, y: 0.012, w: 0.08, h: 0.018},
    {text: "5G", x: 0.78, y: 0.012, w: 0.04, h: 0.018},
    {text: "87%", x: 0.86, y: 0.012, w: 0.06, h: 0.018},
];
const TAB_BAR = [
    {text: "Home", x: 0.05, y: 0.95, w: 0.1, h: 0.02},
    {text: "Activity", x: 0.3, y: 0.95, w: 0.12, h: 0.02},
    {text: "Trade", x: 0.55, y: 0.95, w: 0.1, h: 0.02},
    {text: "Settings", x: 0.78, y: 0.95, w: 0.14, h: 0.02},
];
const phone = (lines) => [...STATUS_BAR, ...lines, ...TAB_BAR];

const parse = (lines) => parseTradeText(lines, {now: NOW});
const only = (lines) => {
    const {trades, moreTrades} = parse(lines);
    expect(moreTrades).toBe(false);
    expect(trades).toHaveLength(1);
    return trades[0];
};

// every field the server reads, so a test states the whole answer
const EMPTY = {
    action: null, asset_type: null, symbol: null, exchange: null, name: null, quantity: null, price: null,
    total: null, currency: null, date: null, timezone: null, account_type: null, confidence: "low",
};
const fields = (changes) => ({...EMPTY, ...changes});

describe("parseTradeText: order screens", () => {
    it.each([
        ["Wealthsimple order details", phone(screen([
            "Done",
            "XEQT",
            "iShares Core Equity ETF Portfolio",
            "Market buy",
            ["Status", "Filled"],
            ["Account", "TFSA"],
            ["Filled", "Oct 30, 2026 2:05 PM EDT"],
            ["Shares", "10"],
            ["Average price", "$31.24"],
            ["Exchange", "TSX"],
            ["Total cost", "$312.40"],
            "Share",
        ])), fields({
            action: "BUY", asset_type: "stock", symbol: "XEQT", exchange: "TSX",
            name: "iShares Core Equity ETF Portfolio", quantity: 10, price: 31.24, total: 312.4,
            date: "2026-10-30 14:05", timezone: "EDT", account_type: "TFSA", confidence: "high",
        })],

        // Tesseract without coordinates, OCR noise: "l0", "pr1ce", a stray "~"
        ["Wealthsimple limit sell, flat OCR with noise", [
            "9:41", "< Back", "~", "XEQT", "Limit sell", "Status Filled", "Account Non-registered",
            "Filled Oct 30, 2026 2:05 PM ET", "Quantity l0", "Avg. pr1ce CA$31.24", "Limit price CA$31.00",
            "Estimated total CA$312.40", "Get help",
        ], fields({
            action: "SELL", asset_type: "stock", symbol: "XEQT", quantity: 10, price: 31.24, total: 312.4,
            currency: "CAD", date: "2026-10-30 14:05", timezone: "ET", account_type: "Non-registered",
            confidence: "high",
        })],

        // values on the row below their labels (a stacked layout), US dollars
        ["Wealthsimple stacked layout", phone(screen([
            "AAPL", "Apple Inc.", "Market buy", "Account", "Personal", "Filled", "Oct 30, 2026 10:31 AM ET",
            "Shares", "2.5", "Average price", "US$190.21", "Total cost", "US$475.53",
        ])), fields({
            action: "BUY", asset_type: "stock", symbol: "AAPL", name: "Apple Inc.", quantity: 2.5, price: 190.21,
            total: 475.53, currency: "USD", date: "2026-10-30 10:31", timezone: "ET", account_type: "Personal",
            confidence: "high",
        })],

        // value on the line below each label, no coordinates
        ["Questrade order details", [
            "Action", "Buy", "Symbol", "XEQT.TO", "Description", "ISHARES CORE EQUITY ETF PORTFOLIO", "Quantity",
            "10", "Price", "31.24", "Net amount", "-312.40", "Currency", "CAD", "Transaction date", "10/30/2026",
            "Settlement date", "10/31/2026", "Account #", "51234567",
        ], fields({
            action: "BUY", asset_type: "stock", symbol: "XEQT.TO", exchange: "TSX",
            name: "ISHARES CORE EQUITY ETF PORTFOLIO", quantity: 10, price: 31.24, total: 312.4, currency: "CAD",
            date: "2026-10-30", confidence: "high",
        })],

        ["Questrade sell with a negative quantity", phone(screen([
            ["Action", "Sell"], ["Symbol", "VFV.TO"], ["Quantity", "-5"], ["Price", "120.82"],
            ["Net amount", "604.10"], ["Currency", "CAD"], ["Trade date", "2026-10-29"],
            ["Settlement date", "2026-10-30"], ["Account type", "RRSP"],
        ])), fields({
            action: "SELL", asset_type: "stock", symbol: "VFV.TO", exchange: "TSX", quantity: 5, price: 120.82,
            total: 604.1, currency: "CAD", date: "2026-10-29", account_type: "RRSP", confidence: "high",
        })],

        ["Crypto.com", phone(screen([
            "Buy BTC", "0.0123 BTC", ["Price", "1 BTC = 92,000.00 CAD"], ["Amount", "0.0123 BTC"],
            ["Fee", "CA$0.00"], ["Total", "CA$1,131.60"], ["Date", "30 Oct 2026, 14:05"], ["Status", "Completed"],
        ])), fields({
            action: "BUY", asset_type: "crypto", symbol: "BTC", quantity: 0.0123, price: 92000, total: 1131.6,
            currency: "CAD", date: "2026-10-30 14:05", confidence: "high",
        })],

        ["Coinbase", phone(screen([
            "You bought", "0.01 BTC", ["BTC price", "$92,000.00"], ["Subtotal", "$920.00"],
            ["Coinbase fee", "$4.99"], ["Total", "$924.99"], ["Paid with", "CAD Wallet"],
            ["Date", "Oct 30, 2026 at 2:05 PM"],
        ])), fields({
            action: "BUY", asset_type: "crypto", symbol: "BTC", quantity: 0.01, price: 92000, total: 924.99,
            currency: "CAD", date: "2026-10-30 14:05", confidence: "high",
        })],

        ["Robinhood", phone(screen([
            "AAPL Market Buy", ["Submitted", "Oct 30, 2026"], ["Status", "Filled"],
            ["Entered quantity", "5 shares"], ["Filled", "5 shares at $190.21"], ["Total", "$951.05"],
        ])), fields({
            action: "BUY", asset_type: "stock", symbol: "AAPL", quantity: 5, price: 190.21, total: 951.05,
            date: "2026-10-30", confidence: "high",
        })],

        ["Interactive Brokers", phone(screen([
            ["Symbol", "AAPL"], ["Side", "BUY"], ["Quantity", "10"], ["Fill Price", "190.21"],
            ["Exchange", "NASDAQ"], ["Time", "2026-10-30 14:05:00 EDT"], ["Commission", "1.00 USD"],
            ["Currency", "USD"],
        ])), fields({
            action: "BUY", asset_type: "stock", symbol: "AAPL", exchange: "NASDAQ", quantity: 10, price: 190.21,
            currency: "USD", date: "2026-10-30 14:05", timezone: "EDT", confidence: "high",
        })],

        ["French Wealthsimple with decimal commas", phone(screen([
            "XEQT", "Achat au marché", ["Compte", "CELI"], ["Exécuté le", "30 oct. 2026 14 h 05 HAE"],
            // as Tesseract read it: "Coût" as "Colt", the "$" of the price as "%"
            ["Actions", "40"], ["Prix moyen", "31,24 %"], ["Colt total", "1 249,60 $"],
        ])), fields({
            action: "BUY", asset_type: "stock", symbol: "XEQT", quantity: 40, price: 31.24, total: 1249.6,
            // "heure avancée de l'Est" is sent as EDT, which the server knows
            date: "2026-10-30 14:05", timezone: "EDT", account_type: "TFSA", confidence: "high",
        })],

        ["euros written the European way", phone(screen([
            ["Order type", "Market sell"], ["Symbol", "ASML"], ["Quantity", "3"], ["Price", "612,40 €"],
            ["Total", "1.837,20 €"], ["Date", "28/10/2026 09:15 CET"],
        ])), fields({
            action: "SELL", asset_type: "stock", symbol: "ASML", quantity: 3, price: 612.4, total: 1837.2,
            currency: "EUR", date: "2026-10-28 09:15", timezone: "CET", confidence: "high",
        })],

        ["Wealthsimple crypto order", [
            "BTC", "Bitcoin", "Market buy", "Account Crypto", "Quantity 0.00512", "Price CA$92,103.11",
            "Total CA$471.57", "Date Oct 30 2:05 PM",
        ], fields({
            action: "BUY", asset_type: "crypto", symbol: "BTC", name: "Bitcoin", quantity: 0.00512,
            price: 92103.11, total: 471.57, currency: "CAD", date: "2026-10-30 14:05", account_type: "Crypto",
            confidence: "high",
        })],

        ["Kraken (XBT is Bitcoin)", [
            "Buy XBT/CAD", "Volume 0.01000000", "Price 92,000.0", "Cost 920.00", "Fee 2.39",
            "Time 10/30/2026 14:05:22",
        ], fields({
            action: "BUY", asset_type: "crypto", symbol: "BTC", quantity: 0.01, price: 92000, total: 920,
            currency: "CAD", date: "2026-10-30 14:05", confidence: "high",
        })],

        ["a crypto pair and a GMT offset", phone(screen([
            ["Pair", "ETH/USD"], ["Side", "Sell"], ["Amount", "0.75 ETH"], ["Price", "3,412.50"],
            ["Date", "Oct 29, 2026 18:40 GMT-4"],
        ])), fields({
            action: "SELL", asset_type: "crypto", symbol: "ETH", quantity: 0.75, price: 3412.5, currency: "USD",
            date: "2026-10-29 18:40", timezone: "GMT-4", confidence: "high",
        })],
    ])("%s", (_, lines, expected) => {
        expect(only(lines)).toEqual(expected);
    });
});

describe("parseTradeText: sentences", () => {
    it.each([
        ["Bought 5 AAPL @ $190.21 on Oct 30, 2026", fields({
            action: "BUY", asset_type: "stock", symbol: "AAPL", quantity: 5, price: 190.21, date: "2026-10-30",
            confidence: "high",
        })],
        ["Sold 0.5 ETH for CA$2,000 yesterday", fields({
            action: "SELL", asset_type: "crypto", symbol: "ETH", quantity: 0.5, total: 2000, currency: "CAD",
            date: "2026-10-31", confidence: "high",
        })],
        ["BOT 10 AAPL @ 190.21 USD", fields({
            action: "BUY", asset_type: "stock", symbol: "AAPL", quantity: 10, price: 190.21, currency: "USD",
            confidence: "high",
        })],
        ["You bought 0.01 Bitcoin", fields({
            action: "BUY", asset_type: "crypto", symbol: "BTC", name: "Bitcoin", quantity: 0.01,
            confidence: "medium",
        })],
        ["Bought 10 shares of XEQT today", fields({
            action: "BUY", asset_type: "stock", symbol: "XEQT", quantity: 10, date: "2026-11-01",
            confidence: "medium",
        })],
        ["Sold 12 shares of SHOP.TO at C$150.25 per share", fields({
            action: "SELL", asset_type: "stock", symbol: "SHOP.TO", exchange: "TSX", quantity: 12, price: 150.25,
            currency: "CAD", confidence: "high",
        })],
    ])("%s", (sentence, expected) => {
        expect(only([sentence])).toEqual(expected);
    });

    it("reads a sentence split over two lines by the reader", () => {
        expect(only(["You bought", "0.05 ETH", "for US$170.60"])).toMatchObject({
            action: "BUY", symbol: "ETH", quantity: 0.05, total: 170.6, currency: "USD", confidence: "high",
        });
    });
});

describe("parseTradeText: several trades", () => {
    it("reads a Wealthsimple activity list, each under its day", () => {
        const {trades, moreTrades} = parse(phone(screen([
            "Activity",
            "Today",
            ["XEQT", "$312.40"],
            "Market buy · TFSA",
            ["VFV", "$604.11"],
            "Limit sell · RRSP",
            "Yesterday",
            ["BTC", "$500.00"],
            "Recurring buy",
            ["Dividend · XEQT", "$4.12"],
            ["Deposit", "$1,000.00"],
        ])));
        expect(moreTrades).toBe(false);
        expect(trades).toEqual([
            fields({action: "BUY", asset_type: "stock", symbol: "XEQT", total: 312.4, date: "2026-11-01",
                account_type: "TFSA", confidence: "medium"}),
            fields({action: "SELL", asset_type: "stock", symbol: "VFV", total: 604.11, date: "2026-11-01",
                account_type: "RRSP", confidence: "medium"}),
            fields({action: "BUY", asset_type: "crypto", symbol: "BTC", total: 500, date: "2026-10-31",
                confidence: "medium"}),
        ]);
    });

    it("reads activity sentences with their amounts beside them", () => {
        const {trades} = parse(phone(screen([
            "Oct 30, 2026",
            ["Bought 10 shares of XEQT", "CA$312.40"],
            "TFSA · 2:05 PM",
            ["Sold 0.25 ETH", "CA$1,050.00"],
            "Oct 28, 2026",
            ["Bought 3 shares of AAPL", "US$570.63"],
        ])));
        expect(trades).toEqual([
            fields({action: "BUY", asset_type: "stock", symbol: "XEQT", quantity: 10, total: 312.4,
                currency: "CAD", date: "2026-10-30", account_type: "TFSA", confidence: "high"}),
            fields({action: "SELL", asset_type: "crypto", symbol: "ETH", quantity: 0.25, total: 1050,
                currency: "CAD", date: "2026-10-30", confidence: "high"}),
            fields({action: "BUY", asset_type: "stock", symbol: "AAPL", quantity: 3, total: 570.63,
                currency: "USD", date: "2026-10-28", confidence: "high"}),
        ]);
    });

    it("reads a Questrade activity table column by column", () => {
        const columns = [0.02, 0.17, 0.3, 0.45, 0.58, 0.72, 0.88];
        const row = (cells) => cells.map((text, k) => [text, columns[k]]);
        const {trades} = parse(screen([
            row(["Transaction date", "Action", "Symbol", "Quantity", "Price", "Net amount", "Currency"]),
            row(["10/30/2026", "Buy", "XEQT.TO", "10", "31.24", "-312.40", "CAD"]),
            row(["10/29/2026", "Sell", "VFV.TO", "-5", "120.82", "604.10", "CAD"]),
            row(["10/28/2026", "Dividend", "XEQT.TO", "0", "0.00", "4.12", "CAD"]),
        ]));
        expect(trades).toEqual([
            fields({action: "BUY", asset_type: "stock", symbol: "XEQT.TO", exchange: "TSX", quantity: 10,
                price: 31.24, total: 312.4, currency: "CAD", date: "2026-10-30", confidence: "high"}),
            fields({action: "SELL", asset_type: "stock", symbol: "VFV.TO", exchange: "TSX", quantity: 5,
                price: 120.82, total: 604.1, currency: "CAD", date: "2026-10-29", confidence: "high"}),
        ]);
    });

    it("keeps the first 10 and says there are more", () => {
        const rows = Array.from({length: 12}, (_, i) => [`Bought ${i + 1} shares of XEQT`, `$${(i + 1) * 31}.00`]);
        const {trades, moreTrades} = parse(screen(rows));
        expect(trades).toHaveLength(MAX_TRADES);
        expect(moreTrades).toBe(true);
        expect(trades.map((t) => t.quantity)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    });

    it("takes a header and its summary for one trade, not two", () => {
        expect(only(phone(screen(["Buy BTC", "You bought 0.002 BTC", ["Total", "CA$184.00"]])))).toMatchObject({
            action: "BUY", symbol: "BTC", quantity: 0.002, total: 184, currency: "CAD",
        });
    });
});

describe("parseTradeText: nothing to read", () => {
    it.each([
        ["no lines", []],
        ["not an array", null],
        ["only the status bar and tabs", phone([])],
        ["OCR junk", ["~~ ,. ;", "@#", "|||"]],
        ["a holdings screen (no buy or sell)", phone(screen([
            "XEQT", "iShares Core Equity ETF Portfolio", ["Market value", "$3,748.80"], ["Shares", "120"],
            ["Average cost", "$28.50"], ["Buy", "Sell"],
        ]))],
        ["a quote screen with a Buy button", phone(screen(["AAPL", "$190.21", "+1.2% today", "Buy"]))],
        ["a deposit", phone(screen(["Deposit complete", ["Amount", "$500.00"], ["To", "TFSA"], "Oct 30, 2026"]))],
        ["a news article", ["Bitcoin rallies as markets open", "Shares of tech companies rose on Thursday."]],
        ["a cancelled order", phone(screen([
            "XEQT", "Limit buy", ["Status", "Cancelled"], ["Shares", "10"], ["Limit price", "$30.00"],
        ]))],
        ["a pending order badge", phone(screen(["Buy BTC", "Pending", ["Amount", "0.01 BTC"], ["Total", "$920.00"]]))],
    ])("%s", (_, lines) => {
        expect(parse(lines)).toEqual({trades: [], moreTrades: false});
    });
});

describe("parseTradeText: robustness", () => {
    it("never puts personal details in a field", () => {
        const result = parse(phone(screen([
            ["Name", "John Smith"], ["Email", "john.smith@example.com"], ["Account number", "9876543"],
            ["Account", "TFSA ••••9876"], ["Phone", "416-555-0199"], "Market buy XEQT", ["Shares", "10"],
            ["Price", "$31.24"],
        ])));
        expect(result.trades).toHaveLength(1);
        const sent = JSON.stringify(result);
        for (const secret of ["John", "Smith", "example.com", "9876", "416", "0199"]) {
            expect(sent).not.toContain(secret);
        }
        expect(result.trades[0]).toMatchObject({symbol: "XEQT", account_type: "TFSA", quantity: 10, price: 31.24});
    });

    it("pairs a label with the value beside it even when the reader lists them apart", () => {
        // Tesseract often reads the label column first, then the value column: same rows by their coordinates
        const lines = [
            {text: "Shares", x: 0.05, y: 0.30, w: 0.12, h: 0.02},
            {text: "Average price", x: 0.05, y: 0.35, w: 0.25, h: 0.02},
            {text: "Total cost", x: 0.05, y: 0.40, w: 0.2, h: 0.02},
            {text: "10", x: 0.8, y: 0.302, w: 0.05, h: 0.02},
            {text: "$31.24", x: 0.78, y: 0.351, w: 0.12, h: 0.02},
            {text: "$312.40", x: 0.76, y: 0.399, w: 0.14, h: 0.02},
            {text: "XEQT Market buy", x: 0.05, y: 0.2, w: 0.4, h: 0.03},
        ];
        expect(only(lines)).toMatchObject({symbol: "XEQT", action: "BUY", quantity: 10, price: 31.24, total: 312.4});
    });

    it("doesn't take a value from a row far below its label", () => {
        const lines = [
            {text: "XEQT Market buy", x: 0.05, y: 0.1, w: 0.4, h: 0.03},
            {text: "Shares", x: 0.05, y: 0.2, w: 0.12, h: 0.02},
            {text: "10", x: 0.05, y: 0.6, w: 0.05, h: 0.02}, // a different section
            {text: "Total   $312.40", x: 0.05, y: 0.7, w: 0.5, h: 0.02},
        ];
        expect(only(lines)).toMatchObject({quantity: null, total: 312.4});
    });

    it("says which dollar only when the screen does", () => {
        const base = [["Order type", "Market buy"], ["Symbol", "XEQT"], ["Shares", "10"], ["Price", "$31.24"]];
        expect(only(screen(base)).currency).toBeNull();
        expect(only(screen([...base, ["Currency", "CAD"]])).currency).toBe("CAD");
        expect(only(screen([...base, "All amounts in USD"])).currency).toBe("USD");
        // both dollars on screen: still unknown
        expect(only(screen([...base, "FX: 1 USD = 1.38 CAD"])).currency).toBeNull();
    });

    it("lowers confidence when an amount is missing or the amounts disagree", () => {
        const rows = (extra) => screen([["Order type", "Market buy"], ["Symbol", "XEQT"], ...extra]);
        expect(only(rows([["Shares", "10"], ["Price", "$31.24"]])).confidence).toBe("high");
        expect(only(rows([["Shares", "10"]])).confidence).toBe("medium");
        // 10 × 31.24 is nowhere near 999: one of them was misread
        expect(only(rows([["Shares", "10"], ["Price", "$31.24"], ["Total", "$999.00"]])).confidence).toBe("medium");
        expect(only(rows([["Total", "$312.40"]])).confidence).toBe("medium"); // no quantity
        expect(only(screen([["Symbol", "XEQT"], ["Shares", "10"], "Bought"])).confidence).toBe("medium"); // no amount
    });

    it("needs a buy or sell, an asset and an amount", () => {
        expect(parse(screen([["Symbol", "XEQT"], ["Shares", "10"]])).trades).toEqual([]); // no buy or sell
        expect(parse(screen([["Type", "Market buy"], ["Shares", "10"]])).trades).toEqual([]); // no asset
        expect(parse(screen([["Type", "Market buy"], ["Symbol", "XEQT"]])).trades).toEqual([]); // no amount
        expect(only(screen([["Type", "Market buy"], ["Symbol", "XEQT"], ["Shares", "10"]])).confidence).toBe("medium");
    });

    it("tells a coin from a stock with the same ticker", () => {
        expect(only(["Bought 10 shares of LINK"]).asset_type).toBe("stock");
        expect(only(["Bought 25 LINK"]).asset_type).toBe("crypto");
        expect(only(["Bought 4 UNI"]).asset_type).toBe("stock"); // UNI alone is too common a word to call a coin
        expect(only(["Bought 4 UNI", "Pair UNI/USD"]).asset_type).toBe("crypto");
    });

    it("reads labels OCR got a letter wrong in, but not words that only look alike", () => {
        expect(only(["Market buy", "XEQT", "Quantlty 10", "Sharc price $31.24"])).toMatchObject({
            quantity: 10, price: 31.24,
        });
        // "iShares" is a fund family, not the "Shares" label
        expect(only(["XEQT", "iShares Core Equity ETF Portfolio 12", "Market buy", "Total $312.40"]))
            .toMatchObject({quantity: null, name: "iShares Core Equity ETF Portfolio 12", total: 312.4});
    });

    it("keeps numbers apart that sit side by side", () => {
        expect(only(screen([["Bought 10 shares of XEQT", "312.40 $"]])).quantity).toBe(10);
    });
});

describe("findDateTime", () => {
    it.each([
        ["Oct 30, 2026", "2026-10-30", null, null],
        ["October 30th 2026", "2026-10-30", null, null],
        ["30 Oct 2026", "2026-10-30", null, null],
        ["30 octobre 2026", "2026-10-30", null, null],
        ["mar. 30 oct. 2026", "2026-10-30", null, null], // Tuesday in French, not March 30
        ["2026-10-30T14:05:00", "2026-10-30", "14:05", null],
        ["2026/10/30 9:05 a.m.", "2026-10-30", "09:05", null],
        ["10/30/2026", "2026-10-30", null, null],
        ["30/10/2026", "2026-10-30", null, null],
        ["05/06/2026", null, null, null], // May 6 or June 5
        ["Thu, Oct 30 at 2:05 PM ET", "2026-10-30", "14:05", "ET"],
        ["Oct 30, 2026, 12:00 AM", "2026-10-30", "00:00", null],
        ["Today 14:05 EST", "2026-11-01", "14:05", "EST"],
        ["Yesterday, 11:59 PM PT", "2026-10-31", "23:59", "PT"],
        ["Dec 15", "2025-12-15", null, null], // no year: the last Dec 15, never a future one
        ["30 oct. 2026 14 h 05", "2026-10-30", "14:05", null],
        ["Filled at 2:05 pm et", null, "14:05", null], // "et" in lowercase is a word
        ["Feb 30, 2026", null, null, null],
        ["Shares 10", null, null, null],
    ])("%s", (text, date, time, zone) => {
        expect(findDateTime(text, NOW)).toMatchObject({date, time, zone});
    });
});
