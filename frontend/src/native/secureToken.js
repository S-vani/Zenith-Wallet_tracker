import {isNative, loadPlugin} from "./platform.js";

// In the app the login token also lives in the iOS Keychain. The web view's localStorage can be cleared by iOS
// when the phone is low on space; the Keychain can't, so the user stays signed in. api.js keeps using
// localStorage (synchronously) and this mirrors every change into the Keychain.
const biometric = loadPlugin(() => import("@capgo/capacitor-native-biometric"));
const preferences = loadPlugin(() => import("@capacitor/preferences"));
const SERVER = "ca.zenithwalletracker.app.token";
const INSTALLED_KEY = "installed";

export async function restoreToken() {
    if (!isNative) return;
    try {
        const {NativeBiometric} = await biometric();
        // Keychain items survive deleting the app, but app preferences don't. A missing flag means a fresh install,
        // so a login left over from a previous install is removed instead of silently signing the person back in.
        const {Preferences} = await preferences();
        if ((await Preferences.get({key: INSTALLED_KEY})).value !== "yes") {
            await NativeBiometric.deleteCredentials({server: SERVER}).catch(() => null);
            await Preferences.set({key: INSTALLED_KEY, value: "yes"});
            return;
        }
        if (localStorage.getItem("token")) return;
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
