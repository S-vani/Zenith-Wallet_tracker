// "Scan a screenshot", step 2: the lines of text read on the device (textReader.js) turned into trade fields by rules,
// for POST /transactions/scan/fields. Free and private: no AI and no image leaves the device, only these fields.
// The server checks every field again (and works out a price from the total, looks up TSX listings, converts
// currencies), so this side only has to read what's shown and never guess: anything it can't find is null.
//
// Made for real broker screens and OCR noise: Wealthsimple order details and activity rows, Questrade (Action,
// Symbol, Quantity, Price, Net amount...), Crypto.com ("1 BTC = 92,000.00 CAD"), Coinbase ("You bought 0.01 BTC"),
// Robinhood / IBKR style key-value screens and plain sentences ("Bought 5 AAPL @ $190.21 on Oct 30, 2026").
// A label and its value can be on one row or the value on the row below (rows come from the lines' coordinates).
//
// Privacy: only typed fields come out (a ticker pattern, numbers, a known account type or exchange, a security name
// that looks like one), so names, emails and account numbers on the screen never end up in a field.
// Pure functions, tested in test/tradeTextParser.test.js.

export const MAX_TRADES = 10;
const MAX_TEXT = 100; // the server's limit for every text field
const MAX_QUANTITY = 1e9;

// ---------------------------------------------------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------------------------------------------------

// coin names (lowercase, as written in apps) to tickers
const COIN_NAMES = new Map([
    ["bitcoin cash", "BCH"], ["bitcoin", "BTC"], ["ethereum classic", "ETC"], ["ethereum", "ETH"], ["ether", "ETH"],
    ["solana", "SOL"], ["xrp", "XRP"], ["ripple", "XRP"], ["dogecoin", "DOGE"], ["cardano", "ADA"],
    ["usd coin", "USDC"], ["usdc", "USDC"], ["tether", "USDT"], ["litecoin", "LTC"], ["polkadot", "DOT"],
    ["avalanche", "AVAX"], ["chainlink", "LINK"], ["polygon", "MATIC"], ["shiba inu", "SHIB"], ["pepe", "PEPE"],
    ["stellar", "XLM"], ["tron", "TRX"], ["toncoin", "TON"], ["uniswap", "UNI"], ["cosmos", "ATOM"],
    ["near protocol", "NEAR"], ["aptos", "APT"], ["arbitrum", "ARB"], ["sui", "SUI"], ["bnb", "BNB"],
    ["hedera", "HBAR"], ["internet computer", "ICP"], ["algorand", "ALGO"], ["filecoin", "FIL"], ["aave", "AAVE"],
    ["the graph", "GRT"], ["injective", "INJ"], ["optimism", "OP"],
    ["bonk", "BONK"], ["floki", "FLOKI"], ["dai", "DAI"], ["kaspa", "KAS"], ["monero", "XMR"], ["tezos", "XTZ"],
]);

// tickers that mean a coin even with nothing else saying so
const STRONG_COINS = new Set([
    "BTC", "ETH", "XRP", "DOGE", "ADA", "USDC", "USDT", "LTC", "AVAX", "MATIC", "SHIB", "PEPE", "BCH", "XLM",
    "TRX", "BNB", "ETC", "HBAR", "ICP", "ALGO", "FIL", "AAVE", "MKR", "GRT", "INJ", "BONK", "FLOKI", "ATOM", "SOL",
    "DOT", "LINK", "XMR", "XTZ", "KAS", "DAI", "POL", "XBT",
]);
// other names exchanges give a coin (Kraken writes Bitcoin as XBT)
const COIN_ALIASES = {XBT: "BTC"};
// coin tickers that are also ordinary words or stock tickers: a coin only with a coin amount, pair or name nearby
const WEAK_COINS = new Set(["UNI", "OP", "NEAR", "ARB", "SUI", "TON", "APT", "RENDER"]);
const COIN_TICKERS = new Set([...STRONG_COINS, ...WEAK_COINS]);

const CURRENCY_CODES = new Set(["CAD", "USD", "EUR", "GBP", "AUD", "CHF", "JPY", "NZD", "HKD", "MXN"]);

// all-caps words that are never the traded ticker
const NOT_TICKERS = new Set([
    ...CURRENCY_CODES, "TFSA", "RRSP", "FHSA", "RESP", "LIRA", "RRIF", "RDSP", "BUY", "SELL", "BOT", "SLD", "ETF",
    "ETFS", "TSX", "TSXV", "NYSE", "NASDAQ", "NEO", "CSE", "ARCA", "BATS", "AMEX", "OTC", "CBOE", "ET", "EST", "EDT",
    "PT", "PST", "PDT", "CT", "CST", "CDT", "MT", "MST", "MDT", "AT", "AST", "ADT", "NT", "UTC", "GMT", "AM", "PM",
    "ID", "USA", "US", "CA", "FX", "LTE", "SOS", "OK", "QTY", "AVG", "FEE", "FEES", "NA", "TOTAL", "PRICE", "DATE",
    "TIME", "FILLED", "DONE", "LIMIT", "MARKET", "STOP", "ORDER", "TYPE", "STATUS", "ACCOUNT", "SHARES", "AMOUNT",
    "NET", "GROSS", "VALUE", "CASH", "MARGIN", "NEW", "BACK", "EDIT", "SHARE", "HOME", "MENU", "MORE", "HELP",
    "VIEW", "ALL", "OF", "THE", "AND", "FOR", "ON", "IN", "TO", "A", "I", "X", "DAY", "GTC", "IOC", "FOK", "CAN",
    "CDN", "CAN", "INC", "LTD", "CORP", "LLC", "PLC", "CO", "TRUST", "FUND", "INDEX", "CLASS", "UNITS", "EQUITY",
    "CRYPTO", "STOCK", "STOCKS", "COMPLETED", "PENDING", "CANCELLED", "CANCELED", "SUCCESS", "SUCCESSFUL", "WS",
    "RECEIPT", "DETAILS", "ACTIVITY", "SUMMARY", "CONFIRMATION", "TRADE", "TRADES", "ORDERS", "YOU", "YOUR",
    "BOUGHT", "SOLD", "AT", "PER", "EACH", "NOTE", "WALLET", "SPOT", "PAIR",
]);

// exchanges as written on screens, to the name sent to the server
const EXCHANGES = [
    [/\btoronto stock exchange\b/i, "TSX"], [/\btsx[- ]?v(?:enture)?\b/i, "TSXV"], [/\btsx\b/i, "TSX"],
    [/\bcboe canada\b/i, "NEO"], [/\bneo\b/i, "NEO"], [/\bcse\b/i, "CSE"], [/\bnyse arca\b/i, "NYSE ARCA"],
    [/\bnyse american\b/i, "NYSE AMERICAN"], [/\bnyse\b/i, "NYSE"], [/\bnasdaq\b/i, "NASDAQ"], [/\barca\b/i, "ARCA"],
    [/\bbats\b/i, "BATS"], [/\bamex\b/i, "AMEX"], [/\botc\b/i, "OTC"],
];
// Canadian ticker suffixes (Yahoo style) to their exchange
const SUFFIX_EXCHANGES = {TO: "TSX", V: "TSXV", NE: "NEO", CN: "CSE"};

// account types as shown, matched anywhere ("Market buy · TFSA"); never the account's number or nickname
const ACCOUNT_WORDS = [
    [/\btfsa\b|\bcelia?\b/i, "TFSA"], [/\brrsp\b|\breer\b/i, "RRSP"], [/\bfhsa\b|\bcelia?pp\b/i, "FHSA"],
    [/\bresp\b|\breee\b/i, "RESP"], [/\blira\b/i, "LIRA"], [/\brrif\b|\bferr\b/i, "RRIF"], [/\brdsp\b/i, "RDSP"],
    [/\bnon[- ]?registered\b|\bnon[- ]?enregistr/i, "Non-registered"],
];
// only after an "Account" label (or the word "account"): too common as ordinary words
const ACCOUNT_LABEL_WORDS = [
    [/\bpersonal\b/i, "Personal"], [/\bmargin\b/i, "Margin"], [/\bcash\b/i, "Cash"], [/\bcrypto\b/i, "Crypto"],
    [/\bjoint\b/i, "Joint"],
];

// a security name has one of these, so a person's name under a "Name" label is never taken
const SECURITY_NAME = /\b(inc|corp|corporation|co|ltd|limited|plc|llc|holdings?|group|trust|fund|etf|index|portfolio|shares|class|bank|energy|technologies|systems|ishares|vanguard|bmo|spdr|invesco|global|equity|bond|reit|sa|ag|nv|se)\b\.?/i;

// rows that aren't a trade at all, so they end an activity row (and never give it an amount)
const NOT_A_TRADE = /\b(dividends?|deposits?|withdrawals?|withdrew|transfer(?:red|s)?|interest|rewards?|staking|staked|cashback|referral|bonus|contribution|distribution|fee rebate|airdrop)\b/i;
// an order that didn't execute: skipped, like the AI reader does
const NOT_EXECUTED = /^(?:cancel+ed|rejected|expired|failed|pending|queued|unfilled|not filled|open order|order cancel+ed|annul[ée]e?|en attente)$/i;

// navigation and buttons, never data
const CHROME = new Set([
    "done", "share", "close", "back", "cancel", "edit", "home", "activity", "portfolio", "discover", "settings",
    "search", "accounts", "trade", "transfer", "move", "invest", "spend", "profile", "menu", "more", "help",
    "watchlist", "notifications", "learn", "rewards", "pay", "cards", "explore", "markets", "buy again",
    "repeat order", "view receipt", "download", "contact support", "get help", "order details", "details",
    "transaction details", "trade details", "receipt", "summary", "ok", "got it", "continue", "view all",
    "see all", "cancel order", "save", "print", "export",
]);

// ---------------------------------------------------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------------------------------------------------
// [kind, priority (lower wins when two labels give the same field), phrases]. A row starting with a phrase is a
// label; its value is the rest of the row, or the row below when nothing follows. The longest phrase wins, so
// "account number" (ignored) beats "account" and "settlement date" beats "date".
const LABEL_GROUPS = [
    ["action", 1, ["order type", "transaction type", "type", "action", "side", "activity type", "trade type",
        "order side", "buy/sell", "type d'ordre", "type de transaction", "operation"]],
    ["symbol", 1, ["symbol", "ticker", "ticker symbol", "security", "stock", "asset", "coin", "instrument",
        "symbole", "titre"]],
    ["name", 1, ["name", "security name", "company", "description", "asset name", "nom"]],
    ["quantity", 1, ["shares", "quantity", "qty", "number of shares", "filled quantity", "filled qty",
        "quantity filled", "units", "shares filled", "filled shares", "no of shares", "coins", "executed quantity",
        "exec qty", "size", "volume", "filled volume", "executed volume", "quantite", "nombre d'actions", "actions", "unites", "shares bought", "shares sold"]],
    ["quantity", 3, ["entered quantity", "order quantity", "requested quantity"]],
    ["amount", 2, ["amount", "you receive", "you received", "you get", "you got", "receive", "received",
        "montant"]],
    ["price", 0, ["average price", "avg price", "average fill price", "avg fill price", "price per share",
        "price per unit", "price per coin", "fill price", "filled price", "execution price", "exec price",
        "executed price", "share price", "unit price", "average cost", "avg cost", "cost per share", "prix moyen",
        "prix par action", "prix unitaire", "avg. price", "average share price"]],
    ["price", 1, ["price", "rate", "prix", "cours"]],
    ["price", 4, ["limit price", "stop price", "prix limite"]],
    ["total", 1, ["total cost", "total", "net amount", "estimated total", "order total", "total value",
        "total amount", "value", "order value", "trade value", "total proceeds", "proceeds", "you paid", "you spent",
        "you pay", "spent", "paid", "total notional", "notional", "amount paid", "purchase amount", "cout total",
        "montant net", "montant total", "valeur", "total (cad)", "total (usd)"]],
    ["total", 2, ["subtotal", "gross amount", "cost", "estimated cost", "estimated amount", "estimated",
        "montant brut", "sous-total"]],
    ["fee", 1, ["fee", "fees", "commission", "commissions", "fx fee", "trading fee", "coinbase fee", "network fee",
        "spread", "frais", "transaction fee", "processing fee"]],
    ["currency", 1, ["currency", "settlement currency", "price currency", "devise", "monnaie"]],
    ["date", 0, ["filled", "filled at", "filled on", "trade date", "executed", "executed at", "executed on",
        "execution date", "execution time", "date filled", "filled date", "transaction date", "date de transaction",
        "date d'execution", "execute le"]],
    ["date", 1, ["date", "time", "date & time", "date and time", "date/time", "completed", "completed at",
        "completed on", "timestamp", "when", "heure"]],
    ["date", 2, ["submitted", "submitted at", "created", "created at", "order date", "placed", "placed at",
        "time placed", "order placed", "requested", "requested at"]],
    ["settlement", 1, ["settlement date", "settle date", "settled", "settlement", "settled on",
        "date de reglement", "reglement"]],
    ["account", 1, ["account", "account type", "from account", "to account", "compte", "type de compte",
        "paid with", "pay with"]],
    ["exchange", 1, ["exchange", "market", "listed on", "listing exchange", "primary exchange", "venue",
        "listing", "bourse"]],
    ["status", 1, ["status", "order status", "state", "statut"]],
    ["ignore", 1, ["order id", "order number", "order #", "transaction id", "reference", "reference number",
        "ref", "confirmation", "confirmation number", "account number", "account no", "account #", "account id",
        "email", "name on account", "account holder", "time in force", "good till", "good until", "expiry",
        "expires", "duration", "exchange rate", "fx rate", "conversion rate", "market value", "book value",
        "book cost", "numero de compte", "phone", "address", "username", "user id", "client id",
        "trigger price", "order expiry", "valid until", "representative", "you own", "shares owned", "your position",
        "position", "holdings", "available", "buying power", "balance", "portfolio value", "cash balance"]],
];

const LABELS = LABEL_GROUPS.flatMap(([kind, priority, phrases]) => phrases.map((phrase) => ({
    kind, priority, phrase, words: phrase.split(" ").map(labelWord),
})));

// What a word of a row is compared as: lowercase, no accents, OCR's digit-for-letter mix-ups undone ("pr1ce",
// "Tota1", "|imit"), punctuation dropped ("Avg." = "avg", "Price:" = "price").
function labelWord(token) {
    const swaps = {0: "o", 1: "i", 3: "e", 4: "a", 5: "s", 8: "b", "|": "l"};
    return stripAccents(String(token).toLowerCase())
        .replace(/[0134589|]/g, (c) => swaps[c] ?? c)
        .replace(/[^a-z&#/'()]/g, "")
        .replace(/^[()]+|[()]+$/g, "");
}

function stripAccents(text) {
    return String(text).normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// A label word and a row's word: 2 the same, 1 close enough, 0 not. Close: one letter misread in a longer word
// ("Quantlty", "Sharcs"; four letters will do inside a longer phrase: "Colt total" for "Coût total"), or a plural
// ("Share"/"Shares"). Never a letter more in front: "iShares" isn't "Shares".
function sameWord(label, word, inPhrase = false) {
    if (label === word) return 2;
    if (label.length < (inPhrase ? 4 : 5)) return 0;
    if (label.length === word.length) {
        let differ = 0;
        for (let i = 0; i < label.length; i += 1) if (label[i] !== word[i]) differ += 1;
        return differ <= 1 ? 1 : 0;
    }
    return word === `${label}s` || label === `${word}s` ? 1 : 0;
}

// The label a row starts with: {kind, priority, value}, or null. A leading coin or ticker is skipped ("BTC price").
function matchLabel(text) {
    const tokens = String(text).replace(/([A-Za-zÀ-ɏ)])\s*:\s*/g, "$1: ").split(/\s+/).filter(Boolean);
    const words = tokens.map(labelWord);
    for (const start of [0, 1]) {
        if (start === 1 && !(tokens.length > 1 && /^[A-Z]{2,6}$/.test(tokens[0]))) break;
        let best = null;
        let bestScore = 0;
        for (const label of LABELS) {
            if (label.words.length > words.length - start) continue;
            let score = 0;
            for (let k = 0; k < label.words.length; k += 1) {
                const same = sameWord(label.words[k], words[start + k], label.words.length > 1);
                if (!same) {
                    score = 0;
                    break;
                }
                score += same;
            }
            // longer phrases first, then exact over one-letter-off; a phrase needs one word read exactly
            if (score && label.words.length > 1 && score < label.words.length + 1) score = 0;
            const total = score && label.words.length * 10 + score;
            if (total > bestScore) {
                best = label;
                bestScore = total;
            }
        }
        if (best) {
            const value = tokens.slice(start + best.words.length).join(" ").replace(/^[\s:·•\-–]+/, "").trim();
            return {kind: best.kind, priority: best.priority, phrase: best.phrase, value};
        }
    }
    return null;
}

// ---------------------------------------------------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------------------------------------------------

// OCR reads "10" as "l0" or "1O" now and then: a token of digits with only those letters mixed in is a number
function fixDigits(text) {
    return text.replace(/(^|[\s$€£(])([\dOoIl|]*\d[\dOoIl|]*(?:[.,][\dOoIl|]+)*)(?=$|[\s),%])/g, (all, lead, token) => {
        if (!/[OoIl|]/.test(token)) return all;
        // "l0", "3l.24" and "1O.5" yes; a word ("Il", "Oct") never gets here: the token needs a digit and nothing
        // but digits and those look-alikes
        return lead + token.replace(/[Oo]/g, "0").replace(/[Il|]/g, "1");
    });
}

function cleanText(text) {
    return fixDigits(String(text ?? "")
        .normalize("NFKC") // no-break and narrow spaces (French thousands) become spaces, full-width digits ASCII
        .replace(/[−‒–—]/g, "-")
        .replace(/[‘’]/g, "'")
        .replace(/\s+/g, " ")
        .trim());
}

const finite = (n) => typeof n === "number" && Number.isFinite(n);

// The lines grouped into rows: lines whose middles are within half a line of each other are one row ("Shares" on
// the left, "10" on the right), left to right. Lines without coordinates are a row each, in the order given.
function buildRows(lines) {
    const items = (Array.isArray(lines) ? lines : []).map((line, order) => {
        const text = cleanText(typeof line === "string" ? line : line?.text);
        if (!text || !/[\p{L}\p{N}]/u.test(text)) return null;
        const placed = line && finite(line.y);
        return {
            text, order,
            x: placed && finite(line.x) ? line.x : 0,
            y: placed ? line.y : null,
            w: placed && finite(line.w) ? line.w : 0,
            h: placed && finite(line.h) && line.h > 0 ? line.h : 0.02,
        };
    }).filter(Boolean);

    const placed = items.length > 0 && items.every((item) => item.y !== null);
    let rows;
    if (!placed) {
        rows = items.map((item) => ({segments: [item], y: null, h: 0}));
    } else {
        rows = [];
        const middle = (item) => item.y + item.h / 2;
        for (const item of [...items].sort((a, b) => middle(a) - middle(b) || a.x - b.x)) {
            const row = rows.at(-1);
            if (row && Math.abs(middle(item) - row.middle) < Math.min(item.h, row.h) / 2) {
                row.segments.push(item);
                row.top = Math.min(row.top, item.y);
                row.bottom = Math.max(row.bottom, item.y + item.h);
            } else {
                rows.push({segments: [item], middle: middle(item), h: item.h, top: item.y, bottom: item.y + item.h});
            }
        }
        for (const row of rows) {
            row.y = row.top;
            row.h = row.bottom - row.top;
        }
    }
    rows.forEach((row) => {
        row.segments.sort((a, b) => a.x - b.x);
        // three spaces between the parts of a row, so "10" and "312.40" side by side never read as one number
        row.text = row.segments.map((s) => s.text).join("   ");
    });
    return rows.filter((row, i) => !isChrome(row, i, placed)).map((row, index) => ({...row, index}));
}

const STATUS_BIT = /^(?:\d{1,2}:\d{2}|\d{1,3}\s?%|lte|5g\+?|5ge|4g|3g|wi-?fi|sos|e|[^\p{L}\p{N}]+)$/iu;

// The status bar (the phone's clock, battery, signal) and buttons/tabs
function isChrome(row, index, placed) {
    const top = placed ? row.y < 0.07 : index < 2;
    if (top && row.segments.every((s) => s.text.split(/\s+/).every((bit) => STATUS_BIT.test(bit)))) return true;
    const words = row.text.toLowerCase().replace(/[^\p{L}\p{N} ]/gu, " ").replace(/\s+/g, " ").trim();
    if (CHROME.has(words)) return true;
    // a tab bar: every part is a navigation word ("Home   Activity   Trade   Settings")
    return row.segments.length > 2 && row.segments.every((s) => CHROME.has(s.text.toLowerCase().trim()));
}

// ---------------------------------------------------------------------------------------------------------------------
// Dates and times
// ---------------------------------------------------------------------------------------------------------------------
const MONTHS = {
    jan: 1, january: 1, janv: 1, janvier: 1, feb: 2, february: 2, fev: 2, fevr: 2, fevrier: 2, mar: 3, march: 3,
    mars: 3, apr: 4, april: 4, avr: 4, avril: 4, may: 5, mai: 5, jun: 6, june: 6, juin: 6, jul: 7, july: 7,
    juil: 7, juillet: 7, aug: 8, august: 8, aout: 8, sep: 9, sept: 9, september: 9, septembre: 9, oct: 10,
    october: 10, octobre: 10, nov: 11, november: 11, novembre: 11, dec: 12, december: 12, decembre: 12,
};
const MONTH = `(${Object.keys(MONTHS).sort((a, b) => b.length - a.length).join("|")})\\b\\.?`;
// a time zone right after a time, in capitals ("ET", "EDT", "GMT-4", "UTC+05:30"): "at" or "et" in lowercase is a
// word, not Atlantic or Eastern time
const ZONE_AFTER = /^\s*\(?((?:CEST|CET|EEST|EET|BST|WET|H[AN][EPCRAT]|[ECMPAN][SD]?T|UTC|GMT|Z)(?:\s?[+-]\s?\d{1,2}(?::?\d{2})?)?|(?:UTC|GMT)?[+-]\d{2}:?\d{2})(?![A-Za-z])\)?/;

const DATE_PATTERNS = [
    // 2026-10-30, 2026/10/30
    [/\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?=\b|t)/g, (m) => [m[1], m[2], m[3]]],
    // Oct 30, 2026 / October 30th 2026 / Thu, Oct 30
    [new RegExp(String.raw`\b${MONTH}\s*(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?`, "g"),
        (m) => [m[3], MONTHS[m[1]], m[2]]],
    // 30 Oct 2026 / 30 octobre 2026 / 1er oct.
    [new RegExp(String.raw`\b(\d{1,2})(?:er|st|nd|rd|th)?\s*${MONTH}(?:,?\s+(\d{4})\b)?`, "g"),
        (m) => [m[3], MONTHS[m[2]], m[1]]],
    // 10/30/2026 or 30/10/2026: only when one reading is a real date
    [/\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b/g, (m) => {
        const a = Number(m[1]);
        const b = Number(m[2]);
        const year = m[3].length === 2 ? `20${m[3]}` : m[3];
        if (a === b) return [year, a, b];
        if (a > 12 && b <= 12) return [year, b, a];
        if (b > 12 && a <= 12) return [year, a, b];
        return null; // 05/06/2026: May 6 or June 5, so not a date at all
    }],
];
// French Canada's zones ("heure avancée de l'Est") as the English ones the server knows
const FRENCH_ZONES = {
    HAE: "EDT", HNE: "EST", HAC: "CDT", HNC: "CST", HAR: "MDT", HNR: "MST", HAP: "PDT", HNP: "PST",
    HAA: "ADT", HNA: "AST", HAT: "NDT", HNT: "NST",
};
const TIME_12 = /(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?/gi;
const TIME_24 = /(?<![\d:.,])([01]?\d|2[0-3])(?::|\s?h\s?)([0-5]\d)(?::[0-5]\d)?(?!\d|\s*[ap]\.?\s?m\b)/gi;
const RELATIVE_DAY = /\b(today|yesterday|aujourd'hui|hier)\b/i;

const pad = (n) => String(n).padStart(2, "0");
const dayOf = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

// "YYYY-MM-DD" when it's a real day, else null. A day without a year is this year's, or last year's if this year's
// would be after `now` (a trade is never in the future).
function realDay(year, month, day, now) {
    const m = Number(month);
    const d = Number(day);
    let y = year ? Number(year) : now.getFullYear();
    if (!(m >= 1 && m <= 12 && d >= 1 && d <= 31 && y >= 1970 && y <= 9999)) return null;
    const check = (yy) => {
        const date = new Date(yy, m - 1, d);
        return date.getMonth() === m - 1 && date.getDate() === d ? date : null;
    };
    let date = check(y);
    if (date && !year && dayOf(date) > dayOf(now)) date = check(y -= 1);
    return date ? `${y}-${pad(m)}-${pad(d)}` : null;
}

// The day, time and time zone written in a text: {date, time, zone, spans} (each may be null; spans are the
// [start, end) of every date and time seen, so amounts can skip them). A day with its year beats one without
// ("mar. 30 oct. 2026" is Tuesday October 30, not March 30), then the first one.
export function findDateTime(text, now = new Date()) {
    const source = stripAccents(String(text)); // same length: the text is NFC (cleanText), one letter per accent
    const lower = source.toLowerCase();
    const result = {date: null, time: null, zone: null, spans: []};

    const days = [];
    for (const [pattern, pick] of DATE_PATTERNS) {
        for (const m of lower.matchAll(pattern)) {
            const parts = pick(m);
            const day = parts && realDay(parts[0], parts[1], parts[2], now);
            if (!day) continue;
            days.push({day, withYear: Boolean(parts[0]), index: m.index});
            result.spans.push([m.index, m.index + m[0].length]);
        }
    }
    days.sort((a, b) => Number(b.withYear) - Number(a.withYear) || a.index - b.index);
    result.date = days[0]?.day ?? null;
    if (!result.date) {
        const m = RELATIVE_DAY.exec(lower);
        if (m) {
            const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (/^(yesterday|hier)$/.test(m[1])) day.setDate(day.getDate() - 1);
            result.date = dayOf(day);
            result.spans.push([m.index, m.index + m[0].length]);
        }
    }

    const inSpan = (i) => result.spans.some(([a, b]) => i >= a && i < b);
    const take = (m, hour) => {
        const end = m.index + m[0].length;
        const zone = ZONE_AFTER.exec(source.slice(end));
        result.time = `${pad(hour)}:${m[2]}`;
        const shown = zone ? zone[1].replace(/\s+/g, "") : null;
        result.zone = FRENCH_ZONES[shown] ?? shown;
        result.spans.push([m.index, end + (zone ? zone[0].length : 0)]);
    };
    for (const m of source.matchAll(TIME_12)) {
        const hour = Number(m[1]);
        if (inSpan(m.index) || hour < 1 || hour > 12) continue;
        take(m, (hour % 12) + (m[4].toLowerCase() === "p" ? 12 : 0));
        break;
    }
    if (!result.time) {
        for (const m of source.matchAll(TIME_24)) {
            if (inSpan(m.index)) continue;
            take(m, Number(m[1]));
            break;
        }
    }
    return result;
}

// The text with its dates and times blanked out, so "Oct 30, 2026" or "2:05 PM" is never read as an amount.
function withoutDates(text, now) {
    const {spans} = findDateTime(text, now);
    let out = String(text);
    for (const [a, b] of spans) out = out.slice(0, a) + " ".repeat(b - a) + out.slice(b);
    return out;
}

// ---------------------------------------------------------------------------------------------------------------------
// Numbers and money
// ---------------------------------------------------------------------------------------------------------------------
// 1,234.56 / 1.234,56 / 1234.56 / 1,5 / .5; French screens also write 1 234,56 (spaces between thousands)
const NUMBER = /(?<![\p{L}\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+,\d+|\d+(?:[.,]\d+)?|[.,]\d+)(?!\d)/gu;
const NUMBER_FR = /(?<![\p{L}\d.,])(\d{1,3}(?: \d{3})+(?:,\d+)?|\d{1,3}(?:\.\d{3})+,\d+|\d+(?:,\d+)?|\d+(?:\.\d+)?|,\d+)(?!\d)/gu;

// A matched number as a JS number. One comma with three digits after is thousands ("1,234") except on a French
// screen, where the comma is always the decimal mark.
function toNumber(raw, locale) {
    let text = raw.replace(/[\s']/g, "");
    const comma = text.lastIndexOf(",");
    const dot = text.lastIndexOf(".");
    if (comma >= 0 && dot >= 0) {
        text = comma > dot ? text.replace(/\./g, "").replace(",", ".") : text.replace(/,/g, "");
    } else if (comma >= 0) {
        const decimals = text.length - comma - 1;
        const several = text.indexOf(",") !== comma;
        text = !several && (locale === "fr" || decimals !== 3) ? text.replace(",", ".") : text.replace(/,/g, "");
    } else if (dot >= 0 && text.indexOf(".") !== dot) {
        text = text.replace(/\./g, ""); // 1.234.567
    }
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
}

// The currency written just before or after an amount: "CAD", "USD", "EUR", another code, "$" (which dollar isn't
// said) or null.
function currencyAround(before, after) {
    const b = before.slice(-8).replace(/[\s\-+(]+$/, "");
    const a = after.slice(0, 8).replace(/^[\s)]+/, "");
    let found = null;
    if (/(?:CA|C|CAD|CDN|CAN)\$$/i.test(b)) found = "CAD";
    else if (/(?:US|U|USD)\$$/i.test(b)) found = "USD";
    else if (/€$/.test(b)) found = "EUR";
    else if (/£$/.test(b)) found = "GBP";
    else if (/\b([A-Z]{3})$/.test(b) && CURRENCY_CODES.has(/([A-Z]{3})$/.exec(b)[1])) found = /([A-Z]{3})$/.exec(b)[1];
    else if (/\$$/.test(b)) found = "$";

    let after3 = null;
    if (/^\$\s?CA\b/i.test(a) || /^CA\$/i.test(a)) after3 = "CAD";
    else if (/^\$\s?US\b/i.test(a)) after3 = "USD";
    else if (/^€/.test(a)) after3 = "EUR";
    else if (/^£/.test(a)) after3 = "GBP";
    else if (/^([A-Z]{3})\b/.test(a) && CURRENCY_CODES.has(a.slice(0, 3))) after3 = a.slice(0, 3);
    else if (/^\$/.test(a)) after3 = "$";
    // "$312.40 CAD": the code says which dollar
    if (after3 && after3 !== "$") return after3;
    return found ?? after3;
}

// What follows an amount: "shares", a coin ticker, or null
function unitAfter(after) {
    const a = after.replace(/^\s+/, "");
    if (/^(?:shares?|sh\b|units?|actions?|parts?|unites?)/i.test(a)) return "shares";
    const m = /^([A-Za-z]{2,6})\b/.exec(a);
    if (m && COIN_TICKERS.has(m[1].toUpperCase())) return m[1].toUpperCase();
    const name = coinNameAt(a);
    return name ? name.ticker : null;
}

function coinNameAt(text) {
    const lower = text.toLowerCase();
    for (const [name, ticker] of COIN_NAMES) {
        if (lower.startsWith(name) && !/[a-z]/.test(lower[name.length] ?? "")) return {name, ticker};
    }
    return null;
}

// Every amount in a text: [{value, currency, unit, index, end}], dates and times skipped. Signs are dropped
// (Questrade writes a buy's net amount and a sell's quantity as negatives).
function amounts(text, ctx) {
    const clean = withoutDates(text, ctx.now);
    const pattern = ctx.locale === "fr" ? NUMBER_FR : NUMBER;
    const out = [];
    for (const m of clean.matchAll(pattern)) {
        const value = toNumber(m[1], ctx.locale);
        if (value === null) continue;
        const end = m.index + m[0].length;
        const before = clean.slice(0, m.index);
        const after = clean.slice(end);
        out.push({value: Math.abs(value), currency: currencyAround(before, after), unit: unitAfter(after),
            index: m.index, end});
    }
    return out;
}

const money = (list) => list.find((a) => a.currency) ?? null;

// The screen's number style: French if it writes decimal commas ("312,40 $") more than decimal points
function screenLocale(text) {
    const commas = (text.match(/\d,\d{2}(?!\d)/g) ?? []).length + (text.match(/\d,\d{1,2}\s?(?:\$|€)/g) ?? []).length;
    const dots = (text.match(/\d\.\d{2}(?!\d)/g) ?? []).length;
    return commas > dots ? "fr" : "en";
}

// Currency codes the screen states anywhere ("CAD", "C$", "US$", "BTC/CAD", "Paid with CAD Wallet")
function statedCurrencies(text) {
    const found = new Set();
    for (const m of text.matchAll(/\b(CAD|USD|EUR|GBP|AUD|CHF|JPY)\b/g)) found.add(m[1]);
    if (/(?:\bCA|\bC|\bCDN|\bCAN)\$|\$\s?CA\b/i.test(text)) found.add("CAD");
    if (/(?:\bUS|\bU)\$|\$\s?US\b/i.test(text)) found.add("USD");
    if (/€/.test(text)) found.add("EUR");
    if (/£/.test(text)) found.add("GBP");
    return found;
}

// ---------------------------------------------------------------------------------------------------------------------
// Field readers
// ---------------------------------------------------------------------------------------------------------------------
const BUY_WORDS = /\b(?:buy|bought|purchased?|bot|achat|achete|acheter|acquired|long)\b/i;
const SELL_WORDS = /\b(?:sell|sold|sale|sld|vente|vendu|vendre|disposed)\b/i;

function actionIn(text) {
    const t = stripAccents(text);
    if (/\bbuy again\b|\bsell all\b/i.test(t)) return null; // buttons
    const buy = BUY_WORDS.exec(t);
    const sell = SELL_WORDS.exec(t);
    if (buy && sell) return buy.index < sell.index ? "BUY" : "SELL";
    return buy ? "BUY" : sell ? "SELL" : null;
}

// "XEQT", "SHOP.TO", "BRK.B", "BTC": uppercase, starts with a letter, not a word that's never a ticker
const TICKER = /^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,3})?$/;

function isTicker(token, {allowShort = true} = {}) {
    const t = String(token ?? "").replace(/[,;:()]+$/g, "").replace(/^\(/, "");
    if (!TICKER.test(t)) return false;
    if (!allowShort && t.length < 2) return false;
    return !NOT_TICKERS.has(t) && !NOT_TICKERS.has(t.split(/[.-]/)[0]);
}

function cleanTicker(token) {
    return String(token).replace(/[,;:()]+$/g, "").replace(/^\(/, "").toUpperCase();
}

// a symbol from a "Symbol"/"Ticker" value: "XEQT", "XEQT.TO", "Bitcoin (BTC)", "Shopify Inc. (SHOP)", "BTC/CAD"
function symbolIn(value) {
    const pair = PAIR.exec(value);
    if (pair) return {symbol: pair[1].toUpperCase(), crypto: true, currency: pair[2].toUpperCase()};
    const paren = /\(([A-Z][A-Z0-9.-]{0,9})\)/.exec(value);
    if (paren && isTicker(paren[1])) return {symbol: cleanTicker(paren[1])};
    for (const token of value.split(/\s+/)) {
        if (isTicker(token)) return {symbol: cleanTicker(token)};
    }
    const coin = coinNameAt(value.trim());
    if (coin) return {symbol: coin.ticker, crypto: true};
    return null;
}

const PAIR = /\b([A-Z0-9]{2,10})\s?[/-]\s?(CAD|USD|USDT|USDC|EUR)\b/i;

function accountIn(value, {labelled = false} = {}) {
    for (const [pattern, name] of ACCOUNT_WORDS) if (pattern.test(value)) return name;
    if (labelled || /\baccount\b|\bcompte\b/i.test(value)) {
        for (const [pattern, name] of ACCOUNT_LABEL_WORDS) if (pattern.test(value)) return name;
    }
    return null;
}

function exchangeIn(value) {
    for (const [pattern, name] of EXCHANGES) if (pattern.test(value)) return name;
    return null;
}

function securityNameIn(value) {
    const text = value.trim().replace(/\s{2,}/g, " ");
    if (!text || text.length > MAX_TEXT || /@|\d{4,}/.test(text)) return null; // never an email or an account number
    const coin = coinNameAt(text.toLowerCase());
    if (coin && coin.name.length >= text.length - 1) return text;
    return SECURITY_NAME.test(text) ? text : null;
}

function assetTypeIn(value) {
    if (/\b(crypto(?:currency)?|coin|token)\b/i.test(value)) return "crypto";
    if (/\b(stocks?|etfs?|equity|equities|shares?|actions?|fund)\b/i.test(value)) return "stock";
    return null;
}

// ---------------------------------------------------------------------------------------------------------------------
// One trade
// ---------------------------------------------------------------------------------------------------------------------

// The best value found so far for each field: a lower priority wins, the first one on the screen on a tie.
class Found {
    constructor() {
        this.values = {};
        this.skip = false;
    }

    set(field, value, priority) {
        if (value === null || value === undefined || value === "") return;
        const old = this.values[field];
        if (!old || priority < old.priority) this.values[field] = {value, priority};
    }

    get(field) {
        return this.values[field]?.value ?? null;
    }

    has(field) {
        return field in this.values;
    }
}

// "Shares 10", "Price US$31.24", "Total cost CA$312.40"...: what a labelled value says. True when it was usable
// (so a value read from the row below is used up).
function applyLabel(found, {kind, priority}, value, ctx) {
    const list = () => amounts(value, ctx);
    switch (kind) {
        case "action": {
            const action = actionIn(value);
            found.set("action", action, priority);
            found.set("assetType", assetTypeIn(value), priority + 2);
            return Boolean(action || assetTypeIn(value));
        }
        case "symbol": {
            const s = symbolIn(value);
            if (!s) return false;
            found.set("symbol", s.symbol, priority);
            if (s.crypto) found.set("assetType", "crypto", priority + 1);
            if (s.currency) found.set("pairCurrency", s.currency, priority);
            const name = securityNameIn(value.replace(/\([^)]*\)/g, "").replace(s.symbol, ""));
            found.set("name", name, priority + 1);
            return true;
        }
        case "name": {
            const name = securityNameIn(value);
            found.set("name", name, priority);
            const coin = coinNameAt(value.trim().toLowerCase());
            if (coin) {
                found.set("symbol", coin.ticker, priority + 4);
                found.set("assetType", "crypto", priority + 2);
            }
            return Boolean(name);
        }
        case "quantity":
        case "amount": {
            const all = list();
            const first = all[0];
            if (!first) return false;
            if (first.currency && first.unit !== "shares" && !COIN_TICKERS.has(first.unit)) {
                if (kind === "amount") found.set("total", money(all), priority);
                return kind === "amount";
            }
            found.set("quantity", first, priority);
            if (first.unit && first.unit !== "shares") {
                found.set("symbol", first.unit, priority + 1);
                found.set("assetType", "crypto", priority + 1);
            }
            if (first.unit === "shares") found.set("assetType", "stock", priority + 2);
            return true;
        }
        case "price": {
            const price = priceIn(value, ctx);
            if (!price) return false;
            found.set("price", price, priority);
            if (price.unit && price.unit !== "shares") {
                found.set("symbol", price.unit, priority + 2);
                found.set("assetType", "crypto", priority + 2);
            }
            return true;
        }
        case "total": {
            const all = list();
            const amount = money(all) ?? all[0];
            found.set("total", amount, priority);
            return Boolean(amount);
        }
        case "currency": {
            const code = /\b([A-Z]{3})\b/.exec(value.toUpperCase());
            found.set("currency", code?.[1] ?? null, priority);
            return Boolean(code);
        }
        case "date":
        case "settlement": {
            const when = findDateTime(value, ctx.now);
            if (!when.date && !when.time) return false;
            const p = kind === "settlement" ? 8 : priority;
            found.set("date", when.date, p);
            if (when.time) found.set("time", {time: when.time, zone: when.zone}, kind === "settlement" ? 8 : priority);
            return true;
        }
        case "account": {
            const account = accountIn(value, {labelled: true});
            found.set("account", account, priority);
            // "Paid with CAD Wallet": not an account, but it says which dollar
            return Boolean(account);
        }
        case "exchange": {
            const exchange = exchangeIn(value);
            found.set("exchange", exchange, priority);
            return Boolean(exchange);
        }
        case "status": {
            if (NOT_EXECUTED.test(stripAccents(value).trim())) found.skip = true;
            return true;
        }
        default: // fees, ids, exchange rates: read so their numbers are never taken for something else
            return true;
    }
}

// a price: "US$31.24", "31,24 $", "1 BTC = 92,000.00 CAD", "$190.21 per share"
function priceIn(value, ctx) {
    const eq = /=\s*(.+)$/.exec(value);
    if (eq) {
        const right = amounts(eq[1], ctx);
        const left = amounts(value.slice(0, eq.index), ctx);
        const target = money(right) ?? right[0];
        if (!target) return null;
        const unit = left[0]?.unit ?? unitAfter(value.slice(0, eq.index).replace(/^[\s\d.,]+/, ""));
        return {...target, unit: unit && unit !== "shares" ? unit : null};
    }
    const all = amounts(value, ctx);
    const amount = money(all) ?? all[0];
    return amount ? {...amount, unit: null} : null;
}

// Sentences and free text: "Bought 10 shares of XEQT", "You bought 0.01 BTC", "BOT 10 AAPL @ 190.21",
// "Sold 0.5 ETH for CA$2,000", "Buy BTC", "XEQT Market buy", "5 shares at $190.21", "0.0123 BTC"...
const QTY_SYMBOL = /\b(?:you\s+)?(bought|sold|buy|sell|purchased|bot|sld|achete|vendu)\s+(?:a\s+total\s+of\s+)?(\d[\d.,']*(?: \d{3})*)\s*(shares?|units?|coins?|sh\b\.?|actions?|parts?)?\s*(?:of\s+|de\s+|d')?([A-Za-z][A-Za-z0-9.-]{0,9}(?:\s[a-z]+)?)/i;
const ACTION_SYMBOL = /\b(?:(?:market|limit|stop|recurring)\s+)?(buy|sell|bought|sold)\s+(?:order\s+)?([A-Za-z][A-Za-z0-9.-]{0,9})(?:\s|$)/i;
const SYMBOL_ACTION = /^([A-Z][A-Z0-9.-]{0,9})\s+(?:[·•-]\s*)?(?:(?:market|limit|stop|recurring)\s+)?(buy|sell|bought|sold)\b/i;
const TIMES_PRICE = /(?<![\p{L}\d.,])(\d[\d.,]*)\s*(?:shares?\s*)?[x×]\s*((?:CA|C|US)?\$?\s?\d[\d.,]*)/iu;

// a symbol as written in a sentence (a ticker, or a coin's name)
function sentenceSymbol(raw) {
    const word = String(raw ?? "").trim();
    const coin = coinNameAt(word.toLowerCase());
    if (coin) return {symbol: coin.ticker, crypto: true};
    const token = word.split(/\s/)[0];
    if (isTicker(token)) return {symbol: cleanTicker(token), crypto: false};
    return null;
}

// The action and asset of a row that starts a trade: "Buy BTC", "XEQT Market buy", "Sell order VFV"
function actionHeader(text) {
    const lead = SYMBOL_ACTION.exec(text);
    if (lead && sentenceSymbol(lead[1])) return {action: actionIn(lead[2]), symbol: sentenceSymbol(lead[1])};
    const m = ACTION_SYMBOL.exec(text);
    if (m && sentenceSymbol(m[2])) return {action: actionIn(m[1]), symbol: sentenceSymbol(m[2])};
    return null;
}

// "Bought 10 shares of XEQT" (with "You bought" + "0.01 BTC" on the row below joined in): {action, symbol,
// quantity, shares}
function tradeSentence(text, next, ctx) {
    const joined = next && actionIn(text) && !/\d/.test(text) ? `${text} ${next}` : text;
    const m = QTY_SYMBOL.exec(stripAccents(withoutDates(joined, ctx.now)));
    if (!m) return null;
    const symbol = sentenceSymbol(m[4]);
    const quantity = toNumber(m[2].trim(), ctx.locale);
    if (!symbol || quantity === null || !(quantity > 0)) return null;
    return {action: actionIn(m[1]), symbol, quantity, shares: Boolean(m[3]) && !/coins?/i.test(m[3])};
}

// A row that's only a ticker, or a ticker with an amount beside it ("XEQT   $312.40"): the title of an order
// screen or of an activity row
function leadTicker(row, ctx) {
    const [first, ...rest] = row.text.trim().split(/\s+/);
    if (!/^[A-Z][A-Z0-9.-]{1,9}$/.test(first ?? "") || !isTicker(first, {allowShort: false})) return null;
    const others = withoutDates(rest.join(" "), ctx.now)
        .replace(/\b(?:CA|C|US|CAD|USD|EUR)\b|[$€£%+\-.,\d\s·•()]/g, "");
    return others ? null : cleanTicker(first);
}

function freeText(found, text, next, ctx, {dates = true, amountsToo = true} = {}) {
    const P = 3; // below labels, above loose words
    const clean = withoutDates(text, ctx.now);

    const sentence = tradeSentence(text, next, ctx);
    if (sentence) {
        const {symbol} = sentence;
        found.set("action", sentence.action, P - 1);
        found.set("symbol", symbol.symbol, P - 1);
        found.set("quantity", {value: sentence.quantity, unit: symbol.crypto ? symbol.symbol : null}, P - 1);
        if (sentence.shares) found.set("assetType", "stock", P);
        else if (symbol.crypto || STRONG_COINS.has(symbol.symbol)) found.set("assetType", "crypto", P);
    }
    const header = actionHeader(clean);
    if (header) {
        found.set("action", header.action, P);
        found.set("symbol", header.symbol.symbol, P);
        if (header.symbol.crypto) found.set("assetType", "crypto", P);
    }

    if (amountsToo) {
        const list = amounts(text, ctx);
        // "@ 190.21", "at $190.21", "à 31,24 $"
        const at = /(?:@|\bat\b|\bà\b|\bau prix de\b)\s*([^@]+)$/i.exec(clean);
        if (at) {
            const amount = amounts(at[1], ctx)[0];
            if (amount && !amount.unit) found.set("price", {...amount, unit: null}, P);
        }
        // "$190.21 per share", "31,24 $ par action"
        for (const a of list) {
            const after = clean.slice(a.end, a.end + 16);
            if (/^\s*(?:\$\s*)?(?:\/\s?(?:share|sh|unit|coin)|per\s+(?:share|unit|coin)|each|par action)\b/i.test(after)) {
                found.set("price", {...a, unit: null}, P);
            }
        }
        // "10 x $31.24"
        const times = TIMES_PRICE.exec(clean);
        if (times) {
            const qty = toNumber(times[1], ctx.locale);
            const price = amounts(times[2], ctx)[0];
            if (qty > 0 && price) {
                found.set("quantity", {value: qty, unit: null}, P);
                found.set("price", {...price, unit: null}, P);
            }
        }
        // "1 BTC = 92,000.00 CAD"
        if (/=/.test(clean)) {
            const price = priceIn(clean.slice(Math.max(0, clean.lastIndexOf("=") - 24)), ctx);
            if (price?.unit) {
                found.set("price", price, P);
                found.set("symbol", price.unit, P + 1);
                found.set("assetType", "crypto", P + 1);
            }
        }
        // "for CA$2,000", "for a total of $312.40"
        const forTotal = /\bfor\s+(?:a\s+total\s+of\s+)?(\S.*)$/i.exec(clean);
        if (forTotal) found.set("total", money(amounts(forTotal[1], ctx)), P);

        // "10 shares", "0.0123 BTC" (not the "1 BTC" of a rate)
        for (const a of list) {
            if (/^\s*=/.test(clean.slice(a.end).replace(/^\s*[A-Za-z]{2,6}/, ""))) continue;
            if (a.unit === "shares") {
                found.set("quantity", a, P + 1);
                found.set("assetType", "stock", P + 2);
            } else if (a.unit && !a.currency) {
                found.set("quantity", a, P + 1);
                found.set("symbol", a.unit, P + 2);
                // "4 UNI" alone could be shares of a stock called UNI; "0.5 BTC" is a coin
                if (STRONG_COINS.has(a.unit)) found.set("assetType", "crypto", P + 2);
            }
        }
    }
    const pair = PAIR.exec(text);
    if (pair && !CURRENCY_CODES.has(pair[1].toUpperCase()) && /[A-Za-z]/.test(pair[1])) {
        found.set("symbol", pair[1].toUpperCase(), P + 1);
        found.set("assetType", "crypto", P + 1);
        found.set("pairCurrency", pair[2].toUpperCase(), P + 1);
    }

    // loose words, anywhere; a lone "Buy" or "Sell" is a button (a label's value was read above)
    if (!/^(?:(?:buy|sell)\s*)+$/i.test(text)) found.set("action", actionIn(text), 6);
    found.set("account", accountIn(text), 5);
    found.set("exchange", exchangeIn(text), 5);
    const coin = coinMention(text);
    if (coin) {
        found.set("symbol", coin.ticker, 6);
        found.set("assetType", "crypto", 6);
        found.set("name", securityNameIn(coin.shown), 6);
    }
    if (dates) {
        const when = findDateTime(text, ctx.now);
        found.set("date", when.date, 6);
        if (when.time && when.date) found.set("time", {time: when.time, zone: when.zone}, 6);
    }
}

// a coin's name anywhere in a text: {ticker, shown}
function coinMention(text) {
    const lower = text.toLowerCase();
    for (const [name, ticker] of COIN_NAMES) {
        if (name.length < 4) continue; // "xrp", "bnb", "sui" are found as tickers instead
        const i = lower.search(new RegExp(String.raw`\b${name}\b`));
        if (i >= 0) return {ticker, shown: text.slice(i, i + name.length)};
    }
    return null;
}

// a row that is only a date (an activity list's day heading)
function dateOnlyRow(row, now) {
    const when = findDateTime(row.text, now);
    if (!when.date) return null;
    const rest = stripAccents(withoutDates(row.text, now))
        .replace(/\b(?:mon|tue|wed|thu|fri|sat|sun|lun|mar|mer|jeu|ven|sam|dim)[a-z]*\b\.?/gi, "");
    return /[\p{L}\p{N}]/u.test(rest) ? null : when.date;
}

// Whether a row that looks like a label really is one: a bare label, or one whose value its kind can read
// ("Market buy" starts like the label "Market" but isn't an exchange, so it can be the value of "Type" above it).
function labelWorks(label, ctx) {
    return !label.value || applyLabel(new Found(), label, label.value, ctx);
}

// The fields of one trade from its rows (a whole order screen, or one item of an activity list).
function readTrade(rows, ctx, {fallbackDate = null, listItem = false} = {}) {
    const found = new Found();
    const used = new Set(); // rows read as a label's value
    const kinds = []; // the label kind of each row (or of its value row)

    rows.forEach((row, i) => {
        if (used.has(i)) return;
        const label = matchLabel(row.text);
        if (!label) return;
        let value = label.value;
        let fromNext = false;
        const next = rows[i + 1];
        const nextLabel = next && matchLabel(next.text);
        if (!value && next && !(nextLabel && labelWorks(nextLabel, ctx)) && closeBelow(row, next)) {
            value = next.text;
            fromNext = true;
        }
        // only a label that read its value claims the row ("Filled   5 shares at $190.21" isn't a date, so its
        // amounts are still read below)
        if (value && applyLabel(found, label, value, ctx)) {
            kinds[i] = label.kind;
            if (fromNext) {
                used.add(i + 1);
                kinds[i + 1] = label.kind;
            }
        }
    });

    rows.forEach((row, i) => {
        const kind = kinds[i];
        if (kind === "ignore" || kind === "fee") return; // an order number or a fee is never a quantity or a total
        if (NOT_EXECUTED.test(stripAccents(row.text).trim())) found.skip = true; // a "Cancelled" badge
        freeText(found, row.text, used.has(i + 1) ? null : rows[i + 1]?.text, ctx, {
            dates: kind !== "settlement",
            // a price, total or date row's numbers were read by its label ("Price 1 BTC = ..." has no quantity)
            amountsToo: !["price", "total", "date", "settlement", "currency", "status"].includes(kind),
        });
        const title = leadTicker(row, ctx);
        if (title) {
            found.set("symbol", title, 7);
            // the security's name just under the ticker ("XEQT" / "iShares Core Equity ETF Portfolio")
            const below = rows[i + 1] && !matchLabel(rows[i + 1].text) ? securityNameIn(rows[i + 1].text) : null;
            found.set("name", below, 5);
        }
        // an activity row's amount ("XEQT   $312.40"): the trade's total. Only in lists: on an order screen an
        // unlabelled amount could be anything (the current price, a fee).
        if (listItem && !kind) found.set("total", money(amounts(row.text, ctx)), 8);
    });
    if (fallbackDate) found.set("date", fallbackDate, 9);
    if (ctx.stated.size === 1) found.set("currency", [...ctx.stated][0], 9);
    return finish(found, rows, ctx);
}

// whether a label's value can be the row just below it (close, not a new section far down)
function closeBelow(row, next) {
    if (row.y === null || next.y === null) return true;
    return next.y - (row.y + row.h) < Math.max(row.h, next.h) * 2.5;
}

const round = (n) => (finite(n) ? Number(n.toPrecision(12)) : null);

// The fields as the server takes them, or null when it isn't a trade
function finish(found, rows) {
    if (found.skip) return null;
    const action = found.get("action");
    const qty = found.get("quantity");
    const price = found.get("price");
    const total = found.get("total");
    let symbol = String(found.get("symbol") ?? "").toUpperCase().slice(0, 15);
    // a quote or holdings screen has a ticker, a price and maybe "120 shares", but no buy or sell
    if (!symbol || !action || !(qty || total)) return null;

    // stock or coin: what the screen says ("shares", an exchange, a .TO ticker, "Type: Crypto"), else a ticker
    // that's only ever a coin
    const blockText = rows.map((r) => r.text).join("\n");
    const stockHints = /\b(shares?|actions?)\b/i.test(blockText) || found.has("exchange")
        || /\.(TO|V|NE|CN)$/.test(symbol);
    let assetType = found.get("assetType");
    if (!assetType) assetType = STRONG_COINS.has(symbol) && !stockHints ? "crypto" : "stock";
    else if (assetType === "crypto" && stockHints && !COIN_TICKERS.has(symbol)) assetType = "stock";

    let exchange = found.get("exchange");
    if (assetType === "crypto") {
        exchange = null;
        symbol = symbol.split(/[/-]/)[0];
        symbol = COIN_ALIASES[symbol] ?? symbol;
    } else {
        const suffix = /\.([A-Z]{1,2})$/.exec(symbol);
        if (!exchange && suffix && SUFFIX_EXCHANGES[suffix[1]]) exchange = SUFFIX_EXCHANGES[suffix[1]];
    }

    const quantity = qty && qty.value > 0 && qty.value <= MAX_QUANTITY ? round(qty.value) : null;
    const priceValue = price && price.value > 0 ? round(price.value) : null;
    const totalValue = total && total.value > 0 ? round(total.value) : null;

    // the currency of the price (or of the total): written next to it, else the pair's quote ("BTC/CAD"), the
    // "Currency" label, or the one currency the screen names anywhere. A bare "$" with nothing saying which dollar
    // stays null, like the AI reader.
    const shown = [priceValue && price.currency, totalValue && total.currency].filter(Boolean);
    const currency = shown.find((c) => c !== "$") ?? found.get("pairCurrency") ?? found.get("currency");

    const day = found.get("date");
    const time = found.get("time");
    const date = day ? (time ? `${day} ${time.time}` : day) : null;

    let name = found.get("name");
    if (name && name.toUpperCase() === symbol) name = null;

    let count = [action, symbol, quantity, priceValue ?? totalValue].filter(Boolean).length;
    // the amounts disagree by more than fees could explain: something was misread
    const off = quantity && priceValue && totalValue && Math.abs(quantity * priceValue - totalValue) / totalValue > 0.15;
    if (off && count === 4) count = 3;

    return {
        action: action ?? null,
        asset_type: assetType,
        symbol,
        exchange: exchange ?? null,
        name: name ? name.slice(0, MAX_TEXT) : null,
        quantity,
        price: priceValue,
        total: totalValue,
        currency: currency && /^[A-Z]{3}$/.test(currency) ? currency : null,
        date,
        timezone: time?.zone && date ? time.zone.slice(0, 12) : null,
        account_type: found.get("account") ?? null,
        confidence: count === 4 ? "high" : count === 3 ? "medium" : "low",
    };
}

// ---------------------------------------------------------------------------------------------------------------------
// The screen
// ---------------------------------------------------------------------------------------------------------------------

// Rows that start a trade in an activity list: a sentence with an action and an asset ("Bought 10 shares of
// XEQT"), or a ticker title with the action on the row below ("XEQT   $312.40" + "Market buy · TFSA")
function isAnchor(row, next, ctx) {
    if (tradeSentence(row.text, next?.text, ctx)) return true;
    if (actionHeader(withoutDates(row.text, ctx.now))) return true;
    const label = next && matchLabel(next.text);
    return Boolean(next && leadTicker(row, ctx) && actionIn(next.text) && !(label && labelWorks(label, ctx)));
}

// A table (Questrade's activity page): a header row of three or more labels, then one trade per row, each value
// under its column. Needs the lines' coordinates.
function tableTrades(rows, ctx) {
    const KINDS = new Set(["action", "symbol", "quantity", "price", "total", "date", "settlement", "name",
        "currency", "account", "amount"]);
    const headerIndex = rows.findIndex((row) => row.y !== null && row.segments.length >= 3
        && new Set(row.segments.map((s) => {
            const label = matchLabel(s.text);
            return label && !label.value && KINDS.has(label.kind) ? label.kind : null;
        }).filter(Boolean)).size >= 3);
    if (headerIndex < 0) return null;
    const columns = rows[headerIndex].segments.map((s) => ({text: s.text, middle: s.x + s.w / 2}));
    const trades = [];
    for (const row of rows.slice(headerIndex + 1)) {
        if (row.segments.length < 2) continue;
        const cells = new Map();
        for (const segment of row.segments) {
            const middle = segment.x + segment.w / 2;
            const column = columns.reduce((best, c) => (Math.abs(c.middle - middle) < Math.abs(best.middle - middle)
                ? c : best));
            cells.set(column.text, [cells.get(column.text), segment.text].filter(Boolean).join(" "));
        }
        const cellRows = [...cells].map(([label, value]) => ({text: `${label}   ${value}`, segments: [], y: null, h: 0}));
        const trade = readTrade(cellRows, ctx);
        if (trade) trades.push(trade);
    }
    return trades.length ? trades : null;
}

// Several trades (an activity list), or one (an order's details: each label once)
function splitTrades(rows, ctx) {
    const anchors = rows.map((row, i) => (isAnchor(row, rows[i + 1], ctx) ? i : -1)).filter((i) => i >= 0);
    const phrases = {};
    const kinds = new Set();
    for (const row of rows) {
        const label = matchLabel(row.text);
        if (!label || !["quantity", "price", "total", "amount"].includes(label.kind)) continue;
        kinds.add(label.kind);
        phrases[label.phrase] = (phrases[label.phrase] ?? 0) + 1;
    }
    const repeated = Object.values(phrases).some((n) => n >= 2); // "Quantity" on every card of a list
    if (anchors.length < 2 || (kinds.size >= 2 && !repeated)) {
        const trade = readTrade(rows, ctx);
        return trade ? [trade] : [];
    }

    // each item runs from its anchor (with the title rows just above it) to the next item; a dividend, a deposit
    // or the next day's heading ends it
    const starts = anchors.map((anchor, k) => {
        let start = anchor;
        const floor = k === 0 ? 0 : anchors[k - 1] + 1;
        while (start - 1 >= floor && (leadTicker(rows[start - 1], ctx) || dateOnlyRow(rows[start - 1], ctx.now))) {
            start -= 1;
        }
        return start;
    });
    const trades = [];
    starts.forEach((start, k) => {
        let end = k + 1 < starts.length ? starts[k + 1] : rows.length;
        for (let i = anchors[k] + 1; i < end; i += 1) {
            if (NOT_A_TRADE.test(rows[i].text) || dateOnlyRow(rows[i], ctx.now)) {
                end = i;
                break;
            }
        }
        // the day heading above this item (lists group trades under "Oct 30, 2026", "Yesterday"...)
        let heading = null;
        for (let i = anchors[k]; i >= 0 && !heading; i -= 1) heading = dateOnlyRow(rows[i], ctx.now);
        const trade = readTrade(rows.slice(start, end), ctx, {fallbackDate: heading, listItem: true});
        if (trade) trades.push(trade);
    });

    // a header ("Buy BTC") and its summary ("You bought 0.01 BTC") are one trade, not two
    const merged = [];
    for (const trade of trades) {
        const last = merged.at(-1);
        if (last && last.symbol === trade.symbol && last.action === trade.action && !last.quantity && !last.price
            && !last.total) {
            merged[merged.length - 1] = mergeTrades(last, trade);
        } else {
            merged.push(trade);
        }
    }
    return merged;
}

function mergeTrades(a, b) {
    const out = {...b};
    for (const key of Object.keys(a)) if (out[key] === null) out[key] = a[key];
    return out;
}

// The trades on a screenshot's lines of text ([{text, x, y, w, h}], top to bottom; coordinates optional, 0..1 from
// the top left): {trades: [...fields], moreTrades} with at most MAX_TRADES trades. `now` dates "Today" and
// "Yesterday" and the year a screen leaves out. {trades: []} when there's nothing trade-like.
export function parseTradeText(lines, {now = new Date()} = {}) {
    const rows = buildRows(lines);
    if (!rows.length) return {trades: [], moreTrades: false};
    const text = rows.map((r) => r.text).join("\n");
    const ctx = {now, locale: screenLocale(text), stated: statedCurrencies(text)};
    const trades = tableTrades(rows, ctx) ?? splitTrades(rows, ctx);
    return {trades: trades.slice(0, MAX_TRADES), moreTrades: trades.length > MAX_TRADES};
}
