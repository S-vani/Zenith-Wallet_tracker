import {useState} from "react";
import TransactionItem from "./TransactionItem.jsx";

const PAGE = 50; // rows drawn at first; "Show more" adds the next batch (a long history stays quick to open)

// The trades to show, already filtered and sorted by the page. onDeleted gets the deleted trade's position in the
// order shown (the page focuses the row now at that position).
function TransactionList({transactions, onChanged, onDeleted, justAdded = null}) {
    const [limit, setLimit] = useState(PAGE);
    // a just-saved trade may be far down a long list: draw up to it
    const justAddedAt = justAdded === null ? -1 : transactions.findIndex((t) => t.id === justAdded);
    const count = Math.min(transactions.length, Math.max(limit, justAddedAt + 1));
    const visible = transactions.slice(0, count);

    return (
        <>
            <div className="transaction-list">
                {visible.map((t, i) => (
                    <TransactionItem key={t.id} transaction={t} index={i} onChanged={onChanged}
                                     onDeleted={() => onDeleted(i)} justAdded={t.id === justAdded}/>
                ))}
            </div>
            {count < transactions.length && (
                <button type="button" className="btn show-more" onClick={() => setLimit(count + PAGE)}>
                    Show more ({transactions.length - count} left)
                </button>
            )}
        </>
    )
}

export default TransactionList
