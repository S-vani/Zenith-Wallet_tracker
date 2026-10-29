// The sign-up form's live checklist. Mirrors UserManager.validate_password in backend/db_models/assets.py, except
// the common-password list, which only the server has (so the checklist never claims to check it).
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

// Each password rule with whether it's met, the same rules the server checks (length, not the email...).
export function passwordChecks(password = "", email = "") {
    const value = String(password);
    // spread counts characters the way Python's len() does, so an emoji is one character, not two
    const length = [...value].length;
    const cleanEmail = String(email).trim().toLowerCase();

    return [
        {
            id: "length",
            label: `${PASSWORD_MIN} to ${PASSWORD_MAX} characters`,
            met: length >= PASSWORD_MIN && length <= PASSWORD_MAX,
        },
        {
            id: "email",
            label: "Not your email address",
            met: value !== "" && (!cleanEmail || value.toLowerCase() !== cleanEmail),
        },
        {
            // the server also refuses a password of only spaces, which reads as the same rule to a person
            id: "repeated",
            label: "Not one character repeated or only spaces",
            met: new Set(value).size > 1 && value.trim() !== "",
        },
    ];
}

// Whether every password rule is met.
export function passwordRulesMet(password, email) {
    return passwordChecks(password, email).every((check) => check.met);
}
