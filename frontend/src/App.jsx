import {Routes, Route, useLocation} from "react-router-dom"
import NavBar from "./NavBar.jsx";
import TransactionPage from "./pages/TransactionPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import HoldingsPage from "./pages/HoldingsPage.jsx";
import LoginPage from "./pages/LoginPage.jsx"
import VerifyPage from "./pages/VerifyPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import HomePage from "./pages/HomePage.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import UserPage from "./pages/UserPage.jsx";


function App() {

    const location = useLocation();

    const hideNav = location.pathname === "/" || location.pathname === "/login" || location.pathname === "/signup" || location.pathname === "/verify";

    return (
        <div>
            {!hideNav && <NavBar/>}
            <main className="main-content">
                <Routes>
                    <Route path="/" element={<HomePage/>}/>
                    <Route path="/Transactions" element={<TransactionPage/>}/>
                    <Route path="/Dashboard" element={<DashboardPage/>}/>
                    <Route path="/Holdings" element={<HoldingsPage/>}/>
                    <Route path="/login" element={<LoginPage/>}/>
                    <Route path="/verify" element={<VerifyPage/>}/>
                    <Route path="/signup" element={<SignupPage/>}/>
                    <Route path="/search" element={<SearchPage/>}/>
                    <Route path="/user" element={<UserPage/>}/>
                </Routes>
            </main>
        </div>

    )
}


export default App
