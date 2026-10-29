import {useLocation} from "react-router-dom";
import {useUser} from "../context/UserContext.jsx";

// Pages that show money need the account (its currency) first. If it couldn't be loaded, every amount shows "—":
// say why and offer Try again, instead of a page of dashes. The dashboard and the Account page show their own.
const OWN_MESSAGE = ["/dashboard", "/user"];

// The banner itself; renders nothing while the account loads fine.
function AccountLoadError() {
    const {error, reload} = useUser();
    const {pathname} = useLocation();
    if (!error || OWN_MESSAGE.includes(pathname)) return null;
    return (
        <div className="alert-error alert-retry account-load-error" role="alert">
            <span>Your account couldn't be loaded, so amounts can't be shown. {error}</span>
            <button type="button" className="btn" onClick={reload}>Try again</button>
        </div>
    );
}

export default AccountLoadError;
