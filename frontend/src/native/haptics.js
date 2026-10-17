import {isNative, loadPlugin} from "./platform.js";

const haptics = loadPlugin(() => import("@capacitor/haptics"));

// Small taps that make the app feel physical: "light" / "medium" for touches, "success" / "warning" / "error"
// for outcomes. Does nothing on the website, and never throws (a missing tap must not break an action).
export async function haptic(kind = "light") {
    if (!isNative) return;
    try {
        const {Haptics, ImpactStyle, NotificationType} = await haptics();
        if (kind === "success") return await Haptics.notification({type: NotificationType.Success});
        if (kind === "warning") return await Haptics.notification({type: NotificationType.Warning});
        if (kind === "error") return await Haptics.notification({type: NotificationType.Error});
        await Haptics.impact({style: kind === "medium" ? ImpactStyle.Medium : ImpactStyle.Light});
    } catch {
        // haptics are a nicety
    }
}
