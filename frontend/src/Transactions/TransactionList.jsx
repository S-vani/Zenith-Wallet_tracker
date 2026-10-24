import TransactionItem from "./TransactionItem.jsx";

// onDeleted gets the deleted trade's position, so the page can move focus to the trade that takes its place
function TransactionList({transactions, onChanged, onDeleted}) {
    return (
        <div className="transaction-list">
            {transactions.map((t, i) => (
                <TransactionItem key={t.id} transaction={t} index={i} onChanged={onChanged}
                                 onDeleted={() => onDeleted(i)}/>
            ))}
        </div>
    )
}

export default TransactionList
