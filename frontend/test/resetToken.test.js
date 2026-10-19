import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {readSavedToken, removeTokenFromAddressBar, saveToken, withoutParam} from "../src/Authentication/resetToken.js";

// The password reset page takes the emailed token out of the address bar so it isn't left in the browser history.

describe("withoutParam", () => {
    it("removes only that parameter and keeps the rest of the address", () => {
        expect(withoutParam("/reset-password?token=abc.def", "token")).toBe("/reset-password");
        expect(withoutParam("/reset-password?token=abc&x=1#top", "token")).toBe("/reset-password?x=1#top");
        expect(withoutParam("/reset-password?x=1&token=abc", "token")).toBe("/reset-password?x=1");
    });

    it("returns the address untouched when there's no token", () => {
        expect(withoutParam("/reset-password", "token")).toBe("/reset-password");
        expect(withoutParam("/reset-password?x=a%20b", "token")).toBe("/reset-password?x=a%20b");
    });
});

describe("reset token in the browser", () => {
    let session;
    let replaceState;

    beforeEach(() => {
        session = new Map();
        vi.stubGlobal("sessionStorage", {
            getItem: (k) => (session.has(k) ? session.get(k) : null),
            setItem: (k, v) => session.set(k, String(v)),
            removeItem: (k) => session.delete(k),
        });
        replaceState = vi.fn();
        vi.stubGlobal("window", {
            location: {pathname: "/reset-password", search: "?token=abc", hash: ""},
            history: {state: {idx: 2, key: "k"}, replaceState},
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it("replaces the address without adding a history entry, keeping the router's state", () => {
        removeTokenFromAddressBar();
        expect(replaceState).toHaveBeenCalledWith({idx: 2, key: "k"}, "", "/reset-password");
    });

    it("does nothing when the address has no token", () => {
        window.location.search = "";
        removeTokenFromAddressBar();
        expect(replaceState).not.toHaveBeenCalled();
    });

    it("keeps a copy for a reload in this tab until it's used", () => {
        saveToken("abc");
        expect(readSavedToken()).toBe("abc");
        saveToken(null);
        expect(readSavedToken()).toBeNull();
    });

    it("copes with storage being blocked", () => {
        vi.stubGlobal("sessionStorage", {
            getItem: () => {
                throw new Error("blocked");
            },
            setItem: () => {
                throw new Error("blocked");
            },
            removeItem: () => {
                throw new Error("blocked");
            },
        });
        expect(() => saveToken("abc")).not.toThrow();
        expect(readSavedToken()).toBeNull();
    });
});
