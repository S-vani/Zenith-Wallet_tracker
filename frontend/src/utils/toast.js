// Tiny toast system: call showToast() from anywhere, the <Toaster/> mounted in App displays it.
// Using a window event means a toast survives the page change that usually follows (e.g. login -> dashboard).

export function showToast(message, {type = "success", duration = 3500} = {}) {
    window.dispatchEvent(new CustomEvent("app:toast", {detail: {message, type, duration}}));
}
