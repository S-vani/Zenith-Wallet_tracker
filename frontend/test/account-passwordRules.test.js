import {describe, expect, it} from "vitest";
import {passwordChecks, passwordRulesMet} from "../src/Authentication/passwordRules.js";

// The sign-up checklist must agree with the backend's validate_password (minus the common-password list).
const met = (password, email) =>
    Object.fromEntries(passwordChecks(password, email).map((check) => [check.id, check.met]));

describe("passwordChecks", () => {
    it("needs 8 to 128 characters", () => {
        expect(met("abc1234").length).toBe(false);
        expect(met("abcd1234").length).toBe(true);
        expect(met("a1".repeat(64)).length).toBe(true);
        expect(met("a1".repeat(64) + "x").length).toBe(false);
    });

    it("counts an emoji as one character, like the server", () => {
        expect(met("😀😀😀😀😀😀😀").length).toBe(false);
        expect(met("😀😀😀😀😀😀😀a").length).toBe(true);
    });

    it("refuses the email address, ignoring case and surrounding spaces", () => {
        expect(met("Jane@Example.com", " jane@example.com ").email).toBe(false);
        expect(met("jane@example.com1", "jane@example.com").email).toBe(true);
        expect(met("something-long", "").email).toBe(true);
    });

    it("refuses one repeated character or only spaces", () => {
        expect(met("aaaaaaaa").repeated).toBe(false);
        expect(met("        ").repeated).toBe(false);
        expect(met(" \t \t \t \t").repeated).toBe(false);
        expect(met("aaaaaaab").repeated).toBe(true);
    });

    it("marks nothing as met for an empty password", () => {
        expect(passwordChecks("", "a@b.co").every((check) => !check.met)).toBe(true);
    });

    it("never lists the common-password rule, which only the server can check", () => {
        expect(passwordChecks("password").map((check) => check.id)).toEqual(["length", "email", "repeated"]);
    });
});

describe("passwordRulesMet", () => {
    it("is true only when every rule passes", () => {
        expect(passwordRulesMet("correct horse", "jane@example.com")).toBe(true);
        expect(passwordRulesMet("short", "jane@example.com")).toBe(false);
        expect(passwordRulesMet("jane@example.com", "jane@example.com")).toBe(false);
    });
});
