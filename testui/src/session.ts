/**
 * Login session storage — deliberately NARROWER than config.ts's rule.
 *
 * The access key (config.ts) is an opaque string with no meaning outside
 * this app, so it lives in localStorage indefinitely. A login token is
 * different: it is a JWT whose claims embed real PII. P1-A's captured
 * `enrol` response and this chunk's own `verify-user` response both put a
 * mobile number, full name and date of birth inside the token's own
 * payload — so persisting it indefinitely on a shared or borrowed test
 * machine is a real exposure this harness does not need to take on.
 *
 * So, decided (not a choice this module makes on its own):
 *   - token         -> sessionStorage. Cleared when the tab closes, rather
 *                      than sitting on disk indefinitely like the access key.
 *   - refreshToken  -> ALSO sessionStorage now (P1-N, reversing the ORIGINAL
 *                      reasoning below on purpose): this project now has a
 *                      real refresh flow (aegle_phr/phr/profile_link.py's
 *                      refresh_token(), spec SS3.43) to actually use it for
 *                      -- the original "nothing has a slot for it" reasoning
 *                      was correct at the time and stopped applying the
 *                      moment a real consumer existed. Same lifetime/
 *                      security posture already accepted for the token
 *                      itself: cleared on tab close, never touches disk.
 *                      ORIGINAL REASONING (P1-A, for the historical record,
 *                      no longer current): "It is valid 15 days and this
 *                      harness has no refresh flow to use it. A tester
 *                      whose 30-minute token expires just logs in again --
 *                      cheap and correct for a throwaway harness."
 *   - loginMethod   -> ALSO sessionStorage now (P1-N): which of this app's
 *                      login screens established the current session.
 *                      Needed to enforce Switch Profile's own gating rule
 *                      (spec SS3.37, quoted in ProfileScreen.tsx) -- "if a
 *                      user logs in using an ABHA Address, they will not be
 *                      able to switch between different users" -- which is
 *                      unenforceable without tracking HOW the session was
 *                      established. Every existing login screen's
 *                      setSession() call now passes one.
 *
 * Guarded the same way config.ts is, so this stays safe to import outside a
 * browser (driving client.ts from Node, as P1-A's verification did).
 */

const TOKEN_STORAGE_KEY = "aegle.phr.session.token";
const ADDRESS_STORAGE_KEY = "aegle.phr.session.abhaAddress";
const REFRESH_TOKEN_STORAGE_KEY = "aegle.phr.session.refreshToken";
const LOGIN_METHOD_STORAGE_KEY = "aegle.phr.session.loginMethod";

/**
 * Which login screen established the current session -- matches how each
 * screen already distinguishes itself internally (PasswordLoginScreen ->
 * "password", MobileLoginScreen -> "mobile", OtpLoginScreen's five route
 * usages in App.tsx -> whichever of the other three fits the identifier
 * that specific route collects). Spec SS3.37's own gating rule (quoted in
 * ProfileScreen.tsx) names four categories -- ABHA Address, ABHA Number,
 * Aadhaar Number, Mobile Number -- and only the address one is excluded
 * from switching; "password" isn't named in the spec's own sentence, but
 * password login IS an ABHA-Address-keyed login (PasswordLoginScreen's own
 * first step is searching BY an ABHA address), so it is grouped with
 * "abha-address" for this gate, not treated as a fifth, ungated category --
 * a judgment call, flagged as such, not a literal reading of the spec text.
 */
export type LoginMethod = "abha-address" | "abha-number" | "aadhaar-number" | "mobile" | "password";

/** Spec SS3.37's own rule, as a predicate -- see the LoginMethod union's own docstring for the "password" judgment call. */
export function canSwitchProfile(loginMethod: LoginMethod | null): boolean {
  return loginMethod === "abha-number" || loginMethod === "aadhaar-number" || loginMethod === "mobile";
}

export const MASKED_TOKEN = "••••";

/**
 * Fired on every setSession()/clearSession() call -- lets App.tsx's own
 * nav (and anything else that cares) react to a login/logout that
 * happened inside some OTHER component's local state, without threading
 * a callback through every login screen. A plain window event rather
 * than React context: session.ts is already guarded to stay importable
 * outside a browser (see this file's own banner), and an event is the
 * simplest thing that works the same way in both places.
 */
export const SESSION_EVENT = "aegle-session-changed";

function hasBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function notifySessionChanged(): void {
  if (!hasBrowser()) return;
  window.dispatchEvent(new Event(SESSION_EVENT));
}

/**
 * Records a logged-in session. `loginMethod` and `refreshToken` are new in
 * P1-N -- see this file's own banner for why both now have a real reason
 * to exist here. `refreshToken` stays optional: several existing login
 * responses in this project don't carry one (e.g. password login's own
 * verify -- see PasswordLoginScreen.tsx), and omitting it there simply
 * means Switch Profile's own request-step re-derives a T-token fresh
 * rather than this app ever having a stale one to fall back on.
 */
export function setSession(abhaAddress: string, token: string, loginMethod: LoginMethod, refreshToken?: string): void {
  if (!hasBrowser()) return;
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    window.sessionStorage.setItem(ADDRESS_STORAGE_KEY, abhaAddress);
    window.sessionStorage.setItem(LOGIN_METHOD_STORAGE_KEY, loginMethod);
    if (refreshToken !== undefined && refreshToken !== "") {
      window.sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
    }
  } catch {
    // Private mode / blocked storage: the screen still reflects "logged in"
    // for this render (the caller also holds the value in React state); it
    // just won't survive a reload. Never throw during a login attempt.
  }
  notifySessionChanged();
}

export function getSessionToken(): string {
  if (!hasBrowser()) return "";
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function getSessionAddress(): string {
  if (!hasBrowser()) return "";
  try {
    return window.sessionStorage.getItem(ADDRESS_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function getRefreshToken(): string {
  if (!hasBrowser()) return "";
  try {
    return window.sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function getLoginMethod(): LoginMethod | null {
  if (!hasBrowser()) return null;
  try {
    const value = window.sessionStorage.getItem(LOGIN_METHOD_STORAGE_KEY);
    const valid: readonly string[] = ["abha-address", "abha-number", "aadhaar-number", "mobile", "password"];
    return value !== null && valid.includes(value) ? (value as LoginMethod) : null;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  if (!hasBrowser()) return;
  try {
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    window.sessionStorage.removeItem(ADDRESS_STORAGE_KEY);
    window.sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    window.sessionStorage.removeItem(LOGIN_METHOD_STORAGE_KEY);
  } catch {
    /* ignore */
  }
  notifySessionChanged();
}

/** For display only — mirrors how client.ts masks the access key. */
export function maskToken(token: string): string {
  return token === "" ? "" : MASKED_TOKEN;
}

/**
 * A FULL session grant, not the short-lived transfer-token shape seen
 * elsewhere in this project (verify_user()'s "T-token": expiresIn 300, no
 * refreshToken) -- distinguished by expiresIn (1800 in the one confirmed
 * example, aegle_phr/phr/aadhaar_enrollment.py's enrol_by_aadhaar() banner)
 * AND the presence of a refreshToken, which a transfer token never
 * carries. Checked defensively: an unexpected shape returns null rather
 * than guessing.
 *
 * Lives here (not local to AadhaarRegisterScreen.tsx, its only current
 * caller) since it is a session-shape question, same category as the rest
 * of this file -- kept ready for whichever other screen next needs to
 * check a response for the same thing, rather than re-implementing it.
 */
export function extractSessionToken(body: unknown): { token: string; expiresIn: number } | null {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return null;
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object") return null;
  const token = (tokens as Record<string, unknown>).token;
  const expiresIn = (tokens as Record<string, unknown>).expiresIn;
  const refreshToken = (tokens as Record<string, unknown>).refreshToken;
  if (typeof token !== "string" || token === "") return null;
  if (typeof expiresIn !== "number" || expiresIn <= 300) return null;
  if (typeof refreshToken !== "string" || refreshToken === "") return null;
  return { token, expiresIn };
}

/**
 * Switch-Profile-Verify's OWN response shape (spec SS3.38, confirmed live
 * via Postman) -- a BARE top-level `token`/`expiresIn`/`refreshToken`, NOT
 * nested under `tokens{}` like extractSessionToken() above (and like every
 * OTHER verify-style response in this project) expects. Forcing this
 * response through extractSessionToken() unmodified would silently return
 * null -- this is a SEPARATE function for a genuinely different shape, not
 * a fix to the existing one (which stays correct for what it already
 * handles). `refreshToken` is returned even if absent/empty (as "") rather
 * than gating on it the way extractSessionToken() does -- this response's
 * own confirmed shape always includes the key, so an empty value here is
 * meaningful data (or a real API quirk), not a sign the whole shape is
 * unrecognised.
 */
export function extractBareSessionToken(body: unknown): { token: string; expiresIn: number; refreshToken: string } | null {
  if (body === null || typeof body !== "object") return null;
  const record = body as Record<string, unknown>;
  const token = record.token;
  const expiresIn = record.expiresIn;
  const refreshToken = record.refreshToken;
  if (typeof token !== "string" || token === "") return null;
  if (typeof expiresIn !== "number") return null;
  return { token, expiresIn, refreshToken: typeof refreshToken === "string" ? refreshToken : "" };
}
