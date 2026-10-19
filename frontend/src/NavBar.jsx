import {useState} from "react";
import {NavLink, useNavigate} from "react-router-dom";
import {logout} from "./services/api.js";
import {showToast} from "./utils/toast.js";
import ConfirmDialog from "./components/ConfirmDialog.jsx";
import {tabOrder} from "./native/tabOrder.js";
import {HoldingsIcon, HomeIcon, LogoutIcon, ProfileIcon, SearchIcon, TransactionsIcon} from "./components/NavIcons.jsx";

import './css/Navbar.css'

const LINKS = [
    {to: "/search", label: "Search", Icon: SearchIcon},
    {to: "/dashboard", label: "Dashboard", Icon: HomeIcon},
    {to: "/transactions", label: "Transactions", Icon: TransactionsIcon},
    {to: "/holdings", label: "Holdings", Icon: HoldingsIcon},
    {to: "/user", label: "Account", Icon: ProfileIcon},
];

// the app's tab bar starts with Dashboard, the screen it opens on; the website keeps this order
const TABS = tabOrder(LINKS);

// same breakpoint as the bottom tab bar in Navbar.css
const PHONE_LAYOUT = "(max-width: 768px)";

function NavBar() {
    const navigate = useNavigate();
    const [confirming, setConfirming] = useState(false);

    const handleLogout = () => {
        setConfirming(false);
        logout();
        window.dispatchEvent(new Event("app:toast-clear")); // e.g. a "Logged in" toast from a moment ago
        showToast("Logged out");
        navigate("/login", {replace: true});
    };

    // on the phone tab bar Log out sits right next to Account, so one stray tap shouldn't sign you out
    const onLogoutClick = () => {
        if (window.matchMedia?.(PHONE_LAYOUT).matches) setConfirming(true);
        else handleLogout();
    };

    return (
        <nav className="navbar" aria-label="Main">
            <div className="navbar-links">
                {TABS.map(({to, label, Icon}) => (
                    <NavLink
                        key={to}
                        to={to}
                        aria-label={label}
                        className={({isActive}) => isActive ? "nav-link active" : "nav-link"}
                    >
                        <Icon/>
                        <span className="nav-tooltip">{label}</span>
                    </NavLink>
                ))}

                <div className="nav-divider" aria-hidden="true"/>

                <button className="nav-link nav-logout" onClick={onLogoutClick} aria-label="Log out">
                    <LogoutIcon/>
                    <span className="nav-tooltip">Log out</span>
                </button>
            </div>

            <ConfirmDialog
                open={confirming}
                title="Log out?"
                message="You'll need to sign in again to see your portfolio."
                confirmLabel="Log out"
                onConfirm={handleLogout}
                onCancel={() => setConfirming(false)}
            />
        </nav>
    )
}

export default NavBar
