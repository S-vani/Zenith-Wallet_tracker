import {useState} from "react";

function SignupForm({onSubmit}) {
    const [form, setForm] = useState({
        "email": "",
        "password": "",
        "name": ""
    });

    const handleChange = async (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    };

    const handleSubmit = async (e) => {
        e.preventDefault()

        onSubmit(form);
    };

    return (
        <div>
            <form onSubmit={handleSubmit}>
                <input name="email" placeholder="Email" onChange={handleChange}/>
                <input name="password" placeholder="Password" onChange={handleChange} autoComplete="off"
                       type="password"/>
                <input name="name" placeholder="Full Name" onChange={handleChange}/>

                <button type="submit">Submit</button>
            </form>
        </div>
    )
}

export default SignupForm
