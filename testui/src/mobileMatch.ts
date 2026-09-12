/**
 * Skip-when-redundant comparison for mobile linking (P1-G) -- Aayush's own
 * rule: if the app already has data proving a fact, don't re-ask for it.
 * enrol/byAadhaar's ABHAProfile.mobile comes back MASKED (confirmed
 * example: "******0903") -- the only thing a masked value can be compared
 * against is its trailing digits, so this compares the last 4 digits of
 * whatever ABDM returned against the last 4 digits of the mobile the
 * tester typed in step 1 (AadhaarRegisterScreen.tsx's own `mobile` state --
 * full plaintext, since it's what the tester typed, not anything ABDM
 * masked).
 *
 * Digits are extracted with a regex rather than assumed to be the last 4
 * characters, so this is robust to however many leading mask characters
 * ABDM actually uses (the confirmed example has 6 asterisks, but that
 * is not asserted elsewhere in this project as a fixed count) and to
 * stray formatting (dashes/spaces) in the typed number.
 */
export function maskedMobileLastFourMatches(profileMobile: string, typedMobile: string): boolean | null {
  const profileDigits = profileMobile.replace(/\D/g, "");
  const typedDigits = typedMobile.replace(/\D/g, "");
  if (profileDigits.length < 4 || typedDigits.length < 4) return null;
  return profileDigits.slice(-4) === typedDigits.slice(-4);
}
