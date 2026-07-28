import {NavLink} from "react-router-dom";

import '../src/css/Navbar.css'

function NavBar() {
    return (
        <nav className="navbar">
            <div className="navbar-links">
                <NavLink to="/search"
                         className={({isActive}) =>
                             isActive ? "nav-link active" : "nav-link"
                         }>


                    {({isActive}) => (
                        <img className="search" src={
                            isActive
                                ? "/assets/search.png"
                                : "/assets/search.png"
                        }
                             alt=""
                        />
                    )}
                </NavLink>

                <NavLink to="/Dashboard"
                         className={({isActive}) =>
                             isActive ? "nav-link active" : "nav-link"
                         }>


                    {({isActive}) => (
                        <img className="home" src={
                            isActive
                                ? "/assets/home_active.png"
                                : "/assets/home.png"
                        }
                             alt=""
                        />
                    )}
                </NavLink>

                <NavLink to="/Transactions"
                         className={({isActive}) =>
                             isActive ? "nav-link active" : "nav-link"
                         }>


                    {({isActive}) => (
                        <img className="transaction" src={
                            isActive
                                ? "/assets/transactions_active.png"
                                : "/assets/transactions.png"
                        }
                             alt=""
                        />
                    )}
                </NavLink>

                <NavLink to="/holdings"
                         className={({isActive}) =>
                             isActive ? "nav-link active" : "nav-link"
                         }>


                    {({isActive}) => (
                        <img className="holding" src={
                            isActive
                                ? "/assets/holdings_active.png"
                                : "/assets/holdings.png"
                        }
                             alt=""
                        />
                    )}
                </NavLink>


                <NavLink to="/user"
                         className={({isActive}) =>
                             isActive ? "nav-link active" : "nav-link"
                         }>


                    {({isActive}) => (
                        <img className="profile" src={
                            isActive
                                ? "/assets/profile_active.png"
                                : "/assets/profile.png"
                        }
                             alt=""
                        />
                    )}
                </NavLink>
            </div>
        </nav>
    )
}

export default NavBar
