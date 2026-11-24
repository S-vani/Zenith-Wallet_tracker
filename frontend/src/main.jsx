import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import {BrowserRouter} from "react-router-dom"
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import {hideSplash, initNative} from "./native/bootstrap.js";
import {applyAmountsHidden} from "./utils/privacy.js";
import {isNative} from "./native/platform.js";
import {initMotionLevel, startFrameWatchdog} from "./motion/motionLevel.js";
import {applyStoredMood, watchPrivacyForMood} from "./motion/mood.js";
import {applyStoredKillSwitch, refreshKillSwitch} from "./motion/killSwitch.js";

// served from our own site, so no third party sees visitors' IPs and the app works offline
import '@fontsource-variable/manrope/index.css'
import '@fontsource-variable/fraunces/opsz.css'
import '@fontsource-variable/fraunces/opsz-italic.css'
// design layer first: tokens, themes, area tints, springs, type, motion (the older css files below use its variables)
import './design/tokens.css'
import './design/themes.css'
import './design/areas.css'
import './design/springs.css'
import './design/type.css'
import './design/motion.css'
import './css/Global.css'
import './css/Home.css'
import './css/Native.css'
import './css/NativeLook.css'

// In the iOS app this first restores the login from the Keychain and reads the Face ID setting;
// on the website it resolves immediately. If anything native is slow or fails, the app still starts after 3 s
// instead of staying on the splash screen. The Face ID setting is then unknown (null): the app starts covered by
// the lock screen whatever the token says, and AppLock waits for the Keychain and the setting before opening it
// (and moves a signed-in person off the login page the 3 s limit may have shown).
applyAmountsHidden(); // privacy mode (the dashboard's eye), before the first paint
initMotionLevel({native: isNative}); // how much movement this device gets (index.html set the same level already)
applyStoredKillSwitch(); // the server's "calm everything" switch, last known value
applyStoredMood(); // the glow's colour from the last known day
watchPrivacyForMood();

const nativeStartup = Promise.race([
    initNative(),
    new Promise((resolve) => setTimeout(() => resolve({lockEnabled: null}), 3000)),
]).catch(() => ({lockEnabled: null}));

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
    startFrameWatchdog(); // a device that can't keep up gets the lite level
    refreshKillSwitch();
});
