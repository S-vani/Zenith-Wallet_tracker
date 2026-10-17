import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import {BrowserRouter} from "react-router-dom"
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import {hideSplash, initNative} from "./native/bootstrap.js";

// served from our own site, so no third party sees visitors' IPs and the app works offline
import '@fontsource/lato/400.css'
import '@fontsource/lato/700.css'
import '@fontsource/lato/900.css'
import './css/Global.css'
import './css/Home.css'
import './css/Native.css'

// In the iOS app this first restores the login from the Keychain and reads the Face ID setting;
// on the website it resolves immediately. If anything native is slow or fails, the app still starts after 3 s
// (signed out, lock off) instead of staying on the splash screen.
const nativeStartup = Promise.race([
    initNative(),
    new Promise((resolve) => setTimeout(() => resolve({lockEnabled: false}), 3000)),
]).catch(() => ({lockEnabled: false}));

nativeStartup.then(({lockEnabled}) => {
    createRoot(document.getElementById('root')).render(
        <StrictMode>
            <ErrorBoundary>
                <BrowserRouter>
                    <App lockEnabled={lockEnabled}/>
                </BrowserRouter>
            </ErrorBoundary>
        </StrictMode>,
    );
    requestAnimationFrame(hideSplash);
});
