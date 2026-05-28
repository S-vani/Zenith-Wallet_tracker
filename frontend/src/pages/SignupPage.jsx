import SignupForm from "../Authentication/SignupForm.jsx";
import {signupAuthentication} from "../services/api";

function SignupPage() {

    return (
        <div>
            <SignupForm onSubmit={signupAuthentication}/>
        </div>
    )
}

export default SignupPage
