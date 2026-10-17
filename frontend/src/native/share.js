import {isNative, loadPlugin} from "./platform.js";

const sharePlugin = loadPlugin(() => import("@capacitor/share"));

// Opens the iOS share sheet (Messages, Mail, copy...). Returns false if sharing isn't possible or was cancelled.
export async function shareText({title, text, url}) {
    if (!isNative) return false;
    try {
        const {Share} = await sharePlugin();
        await Share.share({title, text, url, dialogTitle: title});
        return true;
    } catch {
        return false;
    }
}
