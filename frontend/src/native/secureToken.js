import {isNative, loadPlugin} from "./platform.js";

// In the app the login token also lives in the iOS Keychain. The web view's localStorage can be cleared by iOS
// when the phone is low on space; the Keychain can't, so the user stays signed in. api.js keeps using
// localStorage (synchronously) and this mirrors every change into the Keychain.
const biometric = loadPlugin(() => import("@capgo/capacitor-native-biometric"));
const SERVER = "ca.zenithwalletracker.app.token";

export async function restoreToken() {
    if (!isNative || localStorage.getItem("token")) return;
    try {
        const {NativeBiometric} = await biometric();
        const {password} = await NativeBiometric.getCredentials({server: SERVER});
        if (password) localStorage.setItem("token", password);
    } catch {
        // nothing saved yet: the user is signed out
    }
}

export function saveToken(token) {
    if (!isNative) return;
    biometric()
        .then(({NativeBiometric}) => token
            ? NativeBiometric.setCredentials({username: "zenith", password: token, server: SERVER})
            : NativeBiometric.deleteCredentials({server: SERVER}))
        .catch(() => null);
}
