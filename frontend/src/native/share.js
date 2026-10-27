import {isNative, loadPlugin} from "./platform.js";

const sharePlugin = loadPlugin(() => import("@capacitor/share"));
const filesystemPlugin = loadPlugin(() => import("@capacitor/filesystem"));

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

// Shares a text file ({filename, text}) as a real file: "Save to Files" keeps its name and .csv type and Mail
// attaches it, instead of pasting the text into the message. It's written to the app's cache folder first (iOS
// clears that by itself) and the previous copy is simply overwritten. Returns false if cancelled or impossible.
export async function shareFile({filename, text, title = filename}) {
    if (!isNative) return false;
    try {
        const [{Filesystem, Directory, Encoding}, {Share}] = await Promise.all([filesystemPlugin(), sharePlugin()]);
        const {uri} = await Filesystem.writeFile({
            path: filename, data: text, directory: Directory.Cache, encoding: Encoding.UTF8,
        });
        await Share.share({title, files: [uri], dialogTitle: title});
        return true;
    } catch {
        return false;
    }
}
