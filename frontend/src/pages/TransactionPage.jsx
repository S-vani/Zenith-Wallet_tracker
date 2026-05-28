import {useEffect, useState} from "react";
import {getTransactions} from "../services/api";
import TransactionList from "../Transactions/TransactionList";
import TransactionCreate from "../Transactions/TransactionCreate.jsx"
import TransactionFilter from "../Transactions/TransactionFilter.jsx"
import TransactionSymbolSearch from "../Transactions/TransactionSymbolSearch.jsx";

import '../css/Transaction.css'

function TransactionsPage() {
    const [transactions, setTransactions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [step, setStep] = useState("closed");
    const [symbolData, setSymbolData] = useState({
        "api_id": "",
        "symbol": "",
        "type": ""
    });

    const loadTransactions = async (filters = {}) => {
        try {
            setLoading(true);
            setError(null);

            const data = await getTransactions(filters);
            setTransactions(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadTransactions();
    }, []);

    return (
        <div>
            <h1 className="page-headers">Transactions</h1>

            {loading && <p className="loading">Loading...</p>}
            {error && <p className="error">{error}</p>}
            <TransactionList transactions={transactions}/>

            <div className="filter-add-section">
                <h3>
                    Filters
                </h3>
                <div className="filter-rectangle"></div>
                <TransactionFilter
                    onFiltered={loadTransactions}
                />

                <button className="transaction-button-add" onClick={() => setStep("search")}>
                    Add Transaction
                </button>
            </div>


            {step !== "closed" && (
                <div className="transaction-create-overlay">
                    <div className="transaction-create-box">
                        <button className="transaction-create-close-button" onClick={() => {
                            setStep("closed")
                        }}>
                            <img src="/assets/close.png" alt=""/>
                        </button>

                        <TransactionSymbolSearch
                            onSub={(data) => {
                                setSymbolData(data);
                                setStep("create");
                            }}
                        />

                        {step === "create" && (
                            <TransactionCreate
                                data={symbolData}
                                onClose={() => setStep("closed")}
                                onCreated={() => {
                                    loadTransactions();
                                    setStep("closed");
                                }}
                            />
                        )}

                    </div>
                </div>
            )}
        </div>
    );
}

export default TransactionsPage;
