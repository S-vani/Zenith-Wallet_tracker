import {lazy, Suspense, useEffect} from "react";
import {Routes, Route, Navigate, Outlet, useLocation, useNavigate} from "react-router-dom"
import NavBar from "./NavBar.jsx";
import LoginPage from "./pages/LoginPage.jsx"
import VerifyPage from "./pages/VerifyPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import HomePage from "./pages/HomePage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import OAuthCallbackPage from "./pages/OAuthCallbackPage.jsx";
import Toaster from "./components/Toaster.jsx";
import {UserProvider} from "./context/UserContext.jsx";
import {getToken} from "./services/api.js";

// signed in pages (and the charting library they use) load on demand to keep the landing page fast
const DashboardPage = lazy(() => import("./pages/DashboardPage.jsx"));
const HoldingsPage = lazy(() => import("./pages/HoldingsPage.jsx"));
const TransactionPage = lazy(() => import("./pages/TransactionPage.jsx"));
const SearchPage = lazy(() => import("./pages/SearchPage.jsx"));
const UserPage = lazy(() => import("./pages/UserPage.jsx"));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage.jsx"));


// Wraps every page that needs an account: sends logged out users to /login and adds the nav bar
function ProtectedLayout() {
    const location = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        const onExpired = () => navigate("/login", {replace: true, state: {expired: true, from: location.pathname}});
        window.addEventListener("auth:expired", onExpired);
        return () => window.removeEventListener("auth:expired", onExpired);
    }, [navigate, location.pathname]);

    if (!getToken()) {
        return <Navigate to="/login" replace state={{from: location.pathname}}/>;
    }

    return (
        <UserProvider>
            <NavBar/>
            <main className="main-content">
                <Suspense fallback={<div className="state-message"><div className="spinner"/></div>}>
                    <Outlet/>
                </Suspense>
            </main>
        </UserProvider>
    );
}

function App() {
    return (
        <>
        <Toaster/>
        <Routes>
            <Route path="/" element={<HomePage/>}/>
            <Route path="/login" element={<LoginPage/>}/>
            <Route path="/signup" element={<SignupPage/>}/>
            <Route path="/verify" element={<VerifyPage/>}/>
            <Route path="/auth/callback" element={<OAuthCallbackPage/>}/>
            <Route path="/privacy" element={
                <Suspense fallback={<div className="state-message"><div className="spinner"/></div>}>
                    <PrivacyPage/>
                </Suspense>
            }/>

            <Route element={<ProtectedLayout/>}>
                <Route path="/dashboard" element={<DashboardPage/>}/>
                <Route path="/holdings" element={<HoldingsPage/>}/>
                <Route path="/transactions" element={<TransactionPage/>}/>
                <Route path="/search" element={<SearchPage/>}/>
                <Route path="/user" element={<UserPage/>}/>
            </Route>

            <Route path="*" element={<NotFoundPage/>}/>
        </Routes>
        </>
    )
}


export default App
