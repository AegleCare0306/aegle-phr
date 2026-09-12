/**
 * Shared between AbhaAddressCreationScreen.tsx and AadhaarRegisterScreen.tsx
 * (both now end with an ABHA-address suggestion/creation step) -- pulled out
 * once a second call site needed the identical logic, rather than copied.
 */

export const SANDBOX_SUFFIX = "@sbx";

/**
 * ABDM's own /suggestion endpoint returns bare local-parts (e.g.
 * "rakeshkumar199001"), not full ABHA addresses -- confirmed live,
 * 2026-08-31: submitting a suggestion as-is to isExists/enrol fails with
 * "Invalid ABHA Address". The sandbox domain suffix has to be appended
 * before either call, same "@sbx" convention already used as a placeholder
 * hint everywhere else in this harness. A no-op if the value already has a
 * domain (a suggestion is never expected to, but a manually-typed address
 * might).
 */
export function withSandboxSuffix(value: string): string {
  return value.includes("@") ? value : `${value}${SANDBOX_SUFFIX}`;
}

/**
 * Pulls a list of suggested addresses out of an undocumented body without
 * assuming a shape: accepts a bare array of strings, or the first array of
 * strings found one level down (e.g. {abhaAddressList: [...]}).
 */
export function extractSuggestions(body: unknown): string[] {
  const isStringArray = (v: unknown): v is string[] =>
    Array.isArray(v) && v.every((item) => typeof item === "string");
  if (isStringArray(body)) return body;
  if (body !== null && typeof body === "object") {
    for (const value of Object.values(body as Record<string, unknown>)) {
      if (isStringArray(value)) return value;
    }
  }
  return [];
}
