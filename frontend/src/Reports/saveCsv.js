import {isNative} from "../native/platform.js";
import {shareText} from "../native/share.js";

// Hands the CSV to the person: a normal file download on the website. The iOS web view can't save a blob link,
// so the app opens the share sheet with the CSV text instead (Mail, Notes, Files...). Returns false if cancelled.
export async function saveCsv({filename, text}) {
    if (isNative) {
        return shareText({title: filename, text});
    }
    const url = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
    try {
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
    } finally {
        // revoked on the next tick: some browsers start the download only after click() returns
        setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    return true;
}
