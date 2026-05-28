import {useState} from "react";

function LoginForm({onClose, onSubmit}) {
    const [form, setForm] = useState({
        "username": "",
        "password": ""
    });

    const handleChange = async (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    };

    const handleSubmit = async (e) => {
        e.preventDefault()

        onClose();
        onSubmit(form);
    };

    return (
        <div>
            <form onSubmit={handleSubmit}>
                <input name="username" placeholder="Username" onChange={handleChange}/>
                <input name="password" placeholder="Password" onChange={handleChange} type="password"
                       autoComplete="off"/>

                <button type="submit">Submit</button>
            </form>
        </div>
    )

}

export default LoginForm
