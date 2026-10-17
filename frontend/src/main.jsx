import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import {BrowserRouter} from "react-router-dom"
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import {hideSplash, initNative} from "./native/bootstrap.js";

import './css/Global.css'
import './css/Home.css'
import './css/Native.css'

// In the iOS app this first restores the login from the Keychain and reads the Face ID setting;
// on the website it resolves immediately.
initNative().then(({lockEnabled}) => {
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
