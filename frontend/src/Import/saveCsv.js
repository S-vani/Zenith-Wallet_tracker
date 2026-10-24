import {isNative} from "../native/platform.js";
import {shareText} from "../native/share.js";

// Hand a CSV ({filename, text}) to the person. The website downloads it; the iOS web view can't save a download,
// so the app opens the share sheet instead (Save to Files, Mail, AirDrop...). Returns false if that was cancelled.
export async function saveCsv({filename, text}) {
    if (isNative) {
        return shareText({title: filename, text});
    }
    const url = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000); // after the browser has started the download
    return true;
}
