/**
 * eKYC-lock rule and "has this changed?" diff logic for the profile edit
 * screen (P1-M) -- pure, unit-testable offline, no React/DOM dependency.
 *
 * eKYC-LOCK RULE, quoted directly from spec SS3.42: "In the case of an
 * e-KYC user, KYC details such as name, DOB, and gender will not be
 * updated. However, for a non-e-KYC user, all details will be updated."
 * kycStatus === "VERIFIED" locks exactly these seven fields; any other
 * value (including null/unknown) leaves them editable -- matching the
 * spec's own binary framing (e-KYC vs not), not a guess at intermediate
 * states. address/stateName/districtName/pinCode/stateCode/districtCode/
 * profilePhoto are NEVER locked by this rule -- see aegle_phr/phr/
 * profile.py's own banner for the backend side of this (it does not
 * enforce the rule itself; ABDM and this file are the two real gates).
 */

export const EKYC_LOCKED_FIELDS = [
  "firstName",
  "middleName",
  "lastName",
  "dayOfBirth",
  "monthOfBirth",
  "yearOfBirth",
  "gender",
] as const;

export function isFieldLocked(kycStatus: string | null, field: string): boolean {
  return kycStatus === "VERIFIED" && (EKYC_LOCKED_FIELDS as readonly string[]).includes(field);
}

/**
 * True once at least one of `fields`' current values differs from
 * `baseline`'s -- the "Update" affordance only activates on a real
 * change, per Aayush's explicit instruction. Exact string equality; a
 * field absent from either side is treated as "" (Get Profile's own
 * optional fields may come back as null/absent).
 */
export function hasChanges(
  baseline: Record<string, string>,
  current: Record<string, string>,
  fields: readonly string[],
): boolean {
  return fields.some((field) => (baseline[field] ?? "") !== (current[field] ?? ""));
}
