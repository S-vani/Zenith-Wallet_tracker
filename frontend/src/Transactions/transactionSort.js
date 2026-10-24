// Client-side ordering of the loaded transactions list (the filters still decide what's loaded)

export const TRANSACTION_SORTS = [
    {value: "newest", label: "Newest first"},
    {value: "oldest", label: "Oldest first"},
    {value: "amount", label: "Largest amount"},
];

export const DEFAULT_TRANSACTION_SORT = "newest";

const time = (t) => Date.parse(t.created_at) || 0;
const amount = (t) => Math.abs(Number(t.price_of_one) * Number(t.quantity)) || 0;
const newestFirst = (a, b) => time(b) - time(a);

const COMPARE = {
    newest: newestFirst,
    oldest: (a, b) => time(a) - time(b),
    amount: (a, b) => amount(b) - amount(a) || newestFirst(a, b), // equal amounts: newest first
};

// A new array (the page's state isn't mutated); an unknown sort falls back to newest first. Sort is stable, so
// trades with the same time keep the order the API sent them in.
export function sortTransactions(transactions, sort = DEFAULT_TRANSACTION_SORT) {
    return [...transactions].sort(COMPARE[sort] ?? newestFirst);
}
