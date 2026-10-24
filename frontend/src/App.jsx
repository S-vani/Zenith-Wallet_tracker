import {lazy, Suspense, useEffect} from "react";
import {Routes, Route, Navigate, Outlet, useLocation, useNavigate} from "react-router-dom"
import NavBar from "./NavBar.jsx";
import LoginPage from "./pages/LoginPage.jsx"
import VerifyPage from "./pages/VerifyPage.jsx";
import ForgotPasswordPage from "./pages/ForgotPasswordPage.jsx";
import ResetPasswordPage from "./pages/ResetPasswordPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import HomePage from "./pages/HomePage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import OAuthCallbackPage from "./pages/OAuthCallbackPage.jsx";
import Toaster from "./components/Toaster.jsx";
import DataCredits from "./components/DataCredits.jsx";
import SkipLink from "./components/SkipLink.jsx";
import {UserProvider} from "./context/UserContext.jsx";
import {getToken} from "./services/api.js";
import {isNative} from "./native/platform.js";
import AppLock from "./native/AppLock.jsx";
import OfflineBanner from "./native/OfflineBanner.jsx";
import PullToRefresh from "./native/PullToRefresh.jsx";
import UpdateRequired from "./native/UpdateRequired.jsx";
import AppLinkNavigator from "./native/AppLinkNavigator.jsx";

// signed in pages (and the charting library they use) load on demand to keep the landing page fast
const DashboardPage = lazy(() => import("./pages/DashboardPage.jsx"));
const HoldingsPage = lazy(() => import("./pages/HoldingsPage.jsx"));
const TransactionPage = lazy(() => import("./pages/TransactionPage.jsx"));
const SearchPage = lazy(() => import("./pages/SearchPage.jsx"));
const UserPage = lazy(() => import("./pages/UserPage.jsx"));
const ReportsPage = lazy(() => import("./pages/ReportsPage.jsx"));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage.jsx"));
const TermsPage = lazy(() => import("./pages/TermsPage.jsx"));
const SupportPage = lazy(() => import("./pages/SupportPage.jsx"));
const ImportPage = lazy(() => import("./pages/ImportPage.jsx"));

// shown while a page's code loads; the hidden text tells screen readers what the spinner means
const pageFallback = (
    <div className="state-message" role="status">
        <div className="spinner" aria-hidden="true"/>
        <span className="visually-hidden">Loading…</span>
    </div>
);


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
            {isNative && <PullToRefresh/>}
            <NavBar/>
            <main className="main-content" id="main-content" tabIndex={-1}>
                <Suspense fallback={pageFallback}>
                    <Outlet/>
                </Suspense>
                <DataCredits/>
            </main>
        </UserProvider>
    );
}

function App({lockEnabled = false}) {
    return (
        <>
        <SkipLink/>
        <Toaster/>
        {isNative && <OfflineBanner/>}
        {isNative && <AppLock initiallyEnabled={lockEnabled}/>}
        {isNative && <UpdateRequired/>}
        {isNative && <AppLinkNavigator/>}
        <Routes>
            {/* the app opens straight to your portfolio (or sign in); the marketing page is for the website */}
            <Route path="/" element={isNative
                ? <Navigate to={getToken() ? "/dashboard" : "/login"} replace/>
                : <HomePage/>}/>
            <Route path="/login" element={<LoginPage/>}/>
            <Route path="/signup" element={<SignupPage/>}/>
            <Route path="/verify" element={<VerifyPage/>}/>
            <Route path="/forgot-password" element={<ForgotPasswordPage/>}/>
            <Route path="/reset-password" element={<ResetPasswordPage/>}/>
            <Route path="/auth/callback" element={<OAuthCallbackPage/>}/>
            <Route path="/privacy" element={<Suspense fallback={pageFallback}><PrivacyPage/></Suspense>}/>
            {/* public: App Store Connect's Support URL and the terms sign up agrees to */}
            <Route path="/terms" element={<Suspense fallback={pageFallback}><TermsPage/></Suspense>}/>
            <Route path="/support" element={<Suspense fallback={pageFallback}><SupportPage/></Suspense>}/>

            <Route element={<ProtectedLayout/>}>
                <Route path="/dashboard" element={<DashboardPage/>}/>
                <Route path="/holdings" element={<HoldingsPage/>}/>
                <Route path="/transactions" element={<TransactionPage/>}/>
                <Route path="/search" element={<SearchPage/>}/>
                <Route path="/user" element={<UserPage/>}/>
                <Route path="/import" element={<ImportPage/>}/>
                <Route path="/reports" element={<ReportsPage/>}/>
            </Route>

            <Route path="*" element={<NotFoundPage/>}/>
        </Routes>
        </>
    )
}


export default App
