import {NavLink, useNavigate} from "react-router-dom";
import {logout} from "./services/api.js";
import {HoldingsIcon, HomeIcon, LogoutIcon, ProfileIcon, SearchIcon, TransactionsIcon} from "./components/NavIcons.jsx";

import './css/Navbar.css'

const LINKS = [
    {to: "/search", label: "Search", Icon: SearchIcon},
    {to: "/dashboard", label: "Dashboard", Icon: HomeIcon},
    {to: "/transactions", label: "Transactions", Icon: TransactionsIcon},
    {to: "/holdings", label: "Holdings", Icon: HoldingsIcon},
    {to: "/user", label: "Account", Icon: ProfileIcon},
];

function NavBar() {
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate("/login", {replace: true});
    };

    return (
        <nav className="navbar" aria-label="Main">
            <div className="navbar-links">
                {LINKS.map(({to, label, Icon}) => (
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

                <button className="nav-link nav-logout" onClick={handleLogout} aria-label="Log out">
                    <LogoutIcon/>
                    <span className="nav-tooltip">Log out</span>
                </button>
            </div>
        </nav>
    )
}

export default NavBar
