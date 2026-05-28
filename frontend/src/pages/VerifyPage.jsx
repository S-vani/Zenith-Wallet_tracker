import {useEffect} from "react";
import {useSearchParams} from "react-router-dom";
import {verify} from "../services/api"

function VerifyPage() {
    const [params] = useSearchParams();

    useEffect(() => {
        verify(params);

    }, []);

    return (
        <div>
            <h1>
                Congrats you are now Verified
            </h1>
            <p>
                You may now close this page and login.
            </p>
        </div>

    )
}

export default VerifyPage;
