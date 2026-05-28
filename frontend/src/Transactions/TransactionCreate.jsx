import {useState} from "react";
import {createTransaction} from "../services/api.js";

function TransactionCreate({onClose, onCreated, data}) {
    const [form, setForm] = useState({
        symbol: data.symbol,
        api_id: data.api_id,
        asset_type: data.type,
        quantity: 0.0,
        price_of_one: 0.0,
        action: "BUY",
    });

    const handleChange = (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    }


    const handleSubmit = async (e) => {
        e.preventDefault();

        await createTransaction({
            ...form,
            quantity: Number(form.quantity),
            price_of_one: Number(form.price_of_one)
        });

        onCreated();
        onClose();
    };


    return (
        <div className="transaction-create-wrapper">
            <h2>Create Transaction</h2>

            <form className="create-transaction-form" autoComplete="off" onSubmit={handleSubmit}>
                <div className="quantity-price-buy">
                    <input className="create-transaction-input" autoComplete="off" name="quantity"
                           placeholder="Quantity" onChange={handleChange}/>
                    <input className="create-transaction-input" autoComplete="off" name="price_of_one"
                           placeholder="Price of one" onChange={handleChange}/>

                    <select className="create-select" name="action" onChange={handleChange}>
                        <option value="BUY">BUY</option>
                        <option value="SELL">SELL</option>
                    </select>
                </div>
                <div className="create-transaction-buttons">
                    <button className="create-transaction-button green" type="submit">Submit</button>
                    <button className="create-transaction-button red" type="button" onClick={onClose}>Cancel</button>
                </div>
            </form>
        </div>
    );
}

export default TransactionCreate
