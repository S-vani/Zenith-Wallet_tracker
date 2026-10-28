import {useId, useState} from "react";
import TransactionItem from "./TransactionItem.jsx";
import {DEFAULT_TRANSACTION_SORT, sortTransactions, TRANSACTION_SORTS} from "./transactionSort.js";

// remembered while the app is open, so a filter change that briefly shows "no results" doesn't reset it
let lastSort = DEFAULT_TRANSACTION_SORT;

// onDeleted gets the deleted trade's position in the order shown (the page focuses the row now at that position),
// so the index comes from the sorted list, not the loaded one
function TransactionList({transactions, onChanged, onDeleted, justAdded = null}) {
    const [sort, setSort] = useState(lastSort);
    const sortId = useId();
    const shown = sortTransactions(transactions, sort);

    const changeSort = (e) => {
        lastSort = e.target.value;
        setSort(lastSort);
    };

    return (
        <>
            <div className="transaction-list-toolbar">
                <label htmlFor={sortId} className="filter-label">Sort</label>
                <select id={sortId} className="filter-select transaction-sort" value={sort} onChange={changeSort}>
                    {TRANSACTION_SORTS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                </select>
            </div>
            <div className="transaction-list">
                {shown.map((t, i) => (
                    <TransactionItem key={t.id} transaction={t} index={i} onChanged={onChanged}
                                     onDeleted={() => onDeleted(i)} justAdded={t.id === justAdded}/>
                ))}
            </div>
        </>
    )
}

export default TransactionList
