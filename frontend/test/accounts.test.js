import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {
    ACCOUNT_TYPES,
    ACCOUNT_UNSET,
    accountLabel,
    forgetLastAccount,
    isAccountType,
    loadLastAccount,
    normalizeAccountType,
    saveLastAccount,
} from "../src/utils/accounts.js";
import {createPayload, updatePayload} from "../src/Transactions/tradeForm.js";

describe("account types", () => {
    it("lists the same values as the backend, in order", () => {
        expect(ACCOUNT_TYPES).toEqual([
            {value: "TFSA", label: "TFSA"},
            {value: "RRSP", label: "RRSP"},
            {value: "FHSA", label: "FHSA"},
            {value: "RESP", label: "RESP"},
            {value: "NON_REGISTERED", label: "Non-registered"},
        ]);
        expect(ACCOUNT_UNSET).toBe("UNSET");
    });

    it("labels each type and is safe with nothing set", () => {
        expect(accountLabel("TFSA")).toBe("TFSA");
        expect(accountLabel("NON_REGISTERED")).toBe("Non-registered");
        expect(accountLabel(null)).toBe("—");
        expect(accountLabel(undefined)).toBe("—");
        expect(accountLabel("")).toBe("—");
        expect(accountLabel("LIRA")).toBe("LIRA"); // a type a newer server knows is shown, not hidden
    });

    it("only accepts the known values", () => {
        expect(isAccountType("RRSP")).toBe(true);
        for (const value of ["rrsp", "", "UNSET", null, undefined, "Non-registered"]) {
            expect(isAccountType(value), String(value)).toBe(false);
        }
        expect(normalizeAccountType("FHSA")).toBe("FHSA");
        expect(normalizeAccountType("")).toBeNull();
        expect(normalizeAccountType("junk")).toBeNull();
    });
});

describe("remembered account", () => {
    let store;

    beforeEach(() => {
        store = new Map();
        vi.stubGlobal("localStorage", {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, String(v)),
            removeItem: (k) => store.delete(k),
        });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("starts on nothing, then on the last account saved", () => {
        expect(loadLastAccount()).toBeNull();
        saveLastAccount("RRSP");
        expect(loadLastAccount()).toBe("RRSP");
        saveLastAccount("TFSA");
        expect(loadLastAccount()).toBe("TFSA");
    });

    it("forgets it when \"Not set\" is saved or on sign out", () => {
        saveLastAccount("RRSP");
        saveLastAccount("");
        expect(loadLastAccount()).toBeNull();
        saveLastAccount("RESP");
        forgetLastAccount();
        expect(loadLastAccount()).toBeNull();
        expect(store.size).toBe(0);
    });

    it("ignores a stored value that isn't a known type", () => {
        store.set("lastAccountType", "<script>");
        expect(loadLastAccount()).toBeNull();
    });

    it("keeps working when storage throws or is missing (private mode, blocked site data)", () => {
        vi.stubGlobal("localStorage", {
            getItem: () => {
                throw new Error("SecurityError");
            },
            setItem: () => {
                throw new Error("QuotaExceededError");
            },
            removeItem: () => {
                throw new Error("SecurityError");
            },
        });
        expect(() => saveLastAccount("TFSA")).not.toThrow();
        expect(() => forgetLastAccount()).not.toThrow();
        expect(loadLastAccount()).toBeNull();

        vi.stubGlobal("localStorage", undefined);
        expect(() => saveLastAccount("TFSA")).not.toThrow();
        expect(loadLastAccount()).toBeNull();
    });
});

describe("trade payloads with an account", () => {
    const form = {
        symbol: "AAPL", api_id: "AAPL", asset_type: "stock", action: "BUY",
        quantity: "2", price_of_one: "100", created_at: "2026-10-18T09:00",
    };

    it("sends the picked account with a new trade, and leaves it out when not set", () => {
        expect(createPayload({...form, account_type: "TFSA"}, form.created_at).account_type).toBe("TFSA");
        expect(createPayload({...form, account_type: ""}, form.created_at)).not.toHaveProperty("account_type");
        expect(createPayload(form, form.created_at)).not.toHaveProperty("account_type");
        expect(createPayload({...form, account_type: "junk"}, form.created_at)).not.toHaveProperty("account_type");
    });

    it("sends an edited account, null to clear it, and nothing when unchanged", () => {
        const initial = {action: "BUY", quantity: "2", price_of_one: "100", created_at: form.created_at,
            account_type: "TFSA"};
        expect(updatePayload(initial, {...initial})).toEqual({});
        expect(updatePayload(initial, {...initial, account_type: "RRSP"})).toEqual({account_type: "RRSP"});
        expect(updatePayload(initial, {...initial, account_type: ""})).toEqual({account_type: null});

        const unset = {...initial, account_type: ""};
        expect(updatePayload(unset, {...unset})).toEqual({});
        expect(updatePayload(unset, {...unset, account_type: "NON_REGISTERED"}))
            .toEqual({account_type: "NON_REGISTERED"});
    });
});
