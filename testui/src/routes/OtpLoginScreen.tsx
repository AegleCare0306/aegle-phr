/**
 * Generic OTP-based login screen, used by all five P1-E login methods
 * (ABHA Number via Aadhaar OTP, raw Aadhaar Number, ABHA Number via Mobile
 * OTP, ABHA Address via Mobile OTP, ABHA Address via Email OTP).
 *
 * Deliberately NOT used by MobileLoginScreen.tsx (P1-D), which stays
 * exactly as it is: that screen is already built and live-tested, and
 * folding it into this generic shape would touch working, verified code
 * for a pure-DRY reason with no functional upside -- out of this chunk's
 * scope. This component exists so the five NEW flows don't each become a
 * ~300-line copy of the same request → verify → pick-an-address →
 * verify-user shape; it is structurally identical to MobileLoginScreen,
 * just parametrized by which identifier is being collected and which two
 * backend functions to call.
 *
 * TWO SHAPES, NOT ONE, SELECTED BY `singleAccount` (CORRECTED, confirmed
 * live, Aayush directly): the request→verify→pick-account→verify_user
 * shape above is only correct for the three "abha-login"-scoped routes
 * (ABHA Number via Aadhaar/Mobile OTP, raw Aadhaar Number), whose
 * identifier can resolve to SEVERAL linked ABHA addresses. The two
 * "abha-address-login"-scoped routes (ABHA Address via Mobile/Email OTP)
 * identify a SINGLE, already-specific address -- there is nothing to
 * pick, and calling verify_user() for them is unnecessary: their own
 * verify response already grants a full session directly, the same
 * "abha-address-login" scope family password login already relies on
 * for the identical behaviour. See extractDirectSessionToken()'s own
 * docstring for the full reasoning.
 *
 * SESSION STORAGE: identical rule to every other login screen -- token to
 * sessionStorage via session.ts. Same "Logged in as <address>" shared shape.
 *
 * IDENTIFIER MASKING: Aadhaar numbers and ABHA numbers are personally
 * identifying even though the field itself isn't literally a secret --
 * masked like a password (type="password") when `maskIdentifier` is set.
 * ABHA address and email are left as plain text, matching the existing
 * precedent set by PasswordLoginScreen's own abhaAddress field.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { Check, KeyRound, LogOut, Send } from "lucide-react";

import { loginVerifyUser } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import type { LoginMethod } from "../session";
import { clearSession, getSessionAddress, getSessionToken, maskToken, setSession } from "../session";

/** Reads a named top-level string field out of an otherwise-unknown body. */
function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

interface LinkedUser {
  abhaAddress: string;
  status: string | null;
  kycStatus: string | null;
}

/**
 * verify's expected `users[]` list, read defensively -- this array may
 * carry profiles belonging to people other than whoever is logging in, so
 * ONLY abhaAddress/status/kycStatus are ever pulled out here. A field like
 * fullName or abhaNumber, even if present in the real payload, is never
 * read into this structure -- the raw JSON dump above the picker is the
 * only place that data is shown. Mirrors MobileLoginScreen's own
 * extractUsers() exactly (duplicated here rather than imported, matching
 * this codebase's existing per-screen-helper convention -- see e.g.
 * PasswordLoginScreen's own extractToken(), which isn't shared either).
 */
function extractUsers(body: unknown): LinkedUser[] {
  if (body === null || typeof body !== "object" || !("users" in body)) return [];
  const value = (body as { users: unknown }).users;
  if (!Array.isArray(value)) return [];

  const users: LinkedUser[] = [];
  for (const item of value) {
    if (item === null || typeof item !== "object" || !("abhaAddress" in item)) continue;
    const address = (item as Record<string, unknown>).abhaAddress;
    if (typeof address !== "string" || address === "") continue;
    const status = (item as Record<string, unknown>).status;
    const kycStatus = (item as Record<string, unknown>).kycStatus;
    users.push({
      abhaAddress: address,
      status: typeof status === "string" ? status : null,
      kycStatus: typeof kycStatus === "string" ? kycStatus : null,
    });
  }
  return users;
}

/** Same nested-path reader as MobileLoginScreen's extractTToken() -- see that file for the full story of why this exists. */
function extractTToken(body: unknown): string {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return "";
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("token" in tokens)) return "";
  const value = (tokens as { token: unknown }).token;
  return typeof value === "string" ? value : "";
}

/**
 * Only the raw Aadhaar flow's (SS3.15-16) documented example shows this
 * field. Read defensively for every flow anyway -- a no-op wherever it's
 * absent -- since nothing here assumes any other flow's shape matches
 * that one's exactly. Used ONLY to visually tag the matching entry in the
 * picker; nothing is auto-selected or auto-submitted on its account. See
 * login.py's own banner comment on the raw-Aadhaar flow for why this
 * field gets no behaviour beyond that.
 */
function extractPreferredAddress(body: unknown): string {
  return stringField(body, "preferredAbhaAddress");
}

/**
 * ABHA-Address-based logins (Mobile OTP, Email OTP) skip verify_user()
 * entirely -- CORRECTED, confirmed live, Aayush directly: those two
 * routes use "abha-address-login" scope, the SAME family password login
 * uses (see session.ts's own LoginMethod docstring) -- a single, already-
 * specific ABHA address, with no "list of possible linked accounts to
 * pick from" ambiguity verify_user() exists to resolve (that's genuinely
 * needed for the OTHER three routes here, whose "abha-login" scope
 * starts from a broader identifier -- mobile, Aadhaar number, ABHA
 * number -- that can resolve to several linked addresses). verify's OWN
 * response for these two already grants a full session directly under
 * tokens.token/tokens.refreshToken, mirroring PasswordLoginScreen's own
 * confirmed behaviour for the identical scope family -- reused here
 * rather than guessed at independently.
 */
function extractDirectSessionToken(body: unknown): { token: string; refreshToken: string } | null {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return null;
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("token" in tokens)) return null;
  const token = (tokens as Record<string, unknown>).token;
  const refreshToken = (tokens as Record<string, unknown>).refreshToken;
  if (typeof token !== "string" || token === "") return null;
  return { token, refreshToken: typeof refreshToken === "string" ? refreshToken : "" };
}

/**
 * The ABHA address to store as the session's identity once singleAccount
 * login completes -- NOT always `identifier`: the Email-OTP route's own
 * `identifier` is the typed EMAIL, not an ABHA address (see login.py's
 * own SS3.21-22 comment on why that field is deliberately named `email`).
 * Prefers a users[] entry (matches "there is only one option" -- a
 * single-item list is still a list) or a top-level `abhaAddress` field if
 * either is present in verify's response, falling back to `identifier`
 * only when neither is -- correct for the Mobile-OTP route, where the
 * typed identifier already IS the ABHA address.
 */
function extractLoggedInAddress(body: unknown, identifier: string): string {
  const users = extractUsers(body);
  if (users.length > 0) return users[0].abhaAddress;
  const topLevel = stringField(body, "abhaAddress");
  if (topLevel !== "") return topLevel;
  return identifier;
}

export interface OtpLoginScreenProps {
  /** Shown as the panel heading and in the logged-in state. */
  title: string;
  /** Defaults to a generic key icon -- pass a more specific one (ScanFace, IdCard, AtSign, ...) per route from App.tsx. */
  icon?: LucideIcon;
  /** e.g. "real SMS", "real OTP via UIDAI", "real email" -- filled into the standard warning sentence. */
  otpChannelDescription: string;
  identifierLabel: string;
  identifierPlaceholder: string;
  identifierAutoComplete?: string;
  /** Aadhaar numbers and ABHA numbers: true. ABHA address / email: false (matches PasswordLoginScreen's plain-text abhaAddress precedent). */
  maskIdentifier: boolean;
  /** P1-N: which loginMethod this specific route counts as, for session.ts's own Switch-Profile gate -- see that file's LoginMethod docstring. */
  loginMethod: LoginMethod;
  /**
   * True for the two ABHA-Address routes -- skips the "pick an account" /
   * verify_user() step entirely and completes login straight from
   * verify's own response. See extractDirectSessionToken()'s own
   * docstring for why. Defaults to false (the original three-step
   * request→verify→pick-account→verify_user shape, still correct for the
   * other three routes using this component).
   */
  singleAccount?: boolean;
  requestOtp: (identifier: string) => Promise<ApiResult<AbdmPassthrough>>;
  verifyOtp: (params: { txnId: string; otp: string }) => Promise<ApiResult<AbdmPassthrough>>;
}

export function OtpLoginScreen(props: OtpLoginScreenProps): JSX.Element {
  const { title, icon = KeyRound, otpChannelDescription, identifierLabel, identifierPlaceholder, identifierAutoComplete, maskIdentifier, loginMethod, singleAccount, requestOtp, verifyOtp } = props;

  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [otp, setOtp] = useState("");
  const [txnId, setTxnId] = useState("");

  const [otpResult, setOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [verifyResult, setVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [verifyUserResult, setVerifyUserResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Read once at mount; setSession()/clearSession() below keep this in sync
  // with sessionStorage for the rest of this component's life.
  const [sessionToken, setSessionTokenState] = useState(() => getSessionToken());
  const [sessionAddress, setSessionAddressState] = useState(() => getSessionAddress());

  const users = extractUsers(verifyResult?.data?.body ?? null);
  const verifySucceeded = verifyResult?.data?.ok === true;
  const tToken = extractTToken(verifyResult?.data?.body ?? null);
  const preferredAddress = extractPreferredAddress(verifyResult?.data?.body ?? null);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const pickUser = (abhaAddress: string): void => {
    void run(async () => {
      // tToken is REQUIRED by the backend -- if verify's response didn't
      // carry one, there is nothing correct to send, so this deliberately
      // does not call the endpoint with an empty string and a guaranteed 401.
      if (tToken === "") return;
      const result = await loginVerifyUser({ abhaAddress, txnId, tToken });
      setVerifyUserResult(result);
      const token = stringField(result.data?.body, "token");
      if (result.data?.ok === true && token !== "") {
        setSession(abhaAddress, token, loginMethod, stringField(result.data?.body, "refreshToken"));
        setSessionTokenState(token);
        setSessionAddressState(abhaAddress);
        // Aayush's explicit request -- see PasswordLoginScreen's matching comment.
        navigate("/home");
      }
    });
  };

  if (sessionToken !== "") {
    return (
      <section className="panel">
        <PageHeader icon={icon} title={title} />
        <p className="result">
          <span className="ok">Logged in</span> as <code>{sessionAddress}</code>
        </p>
        <p className="muted">
          Session token: <code>{maskToken(sessionToken)}</code> — held in sessionStorage, clears when
          this tab closes.
        </p>
        <Button
          size="sm"
          icon={LogOut}
          onClick={() => {
            clearSession();
            setSessionTokenState("");
            setSessionAddressState("");
          }}
        >
          Log out
        </Button>
      </section>
    );
  }

  return (
    <section className="panel">
      <PageHeader icon={icon} title={title} />

      <p className="notice notice--warn">
        Requesting an OTP sends a <strong>{otpChannelDescription}</strong> and counts toward
        ABDM&apos;s rate limits. Request it once. If something fails, stop and check the Console
        rather than pressing it again.
      </p>

      <fieldset className="step" disabled={busy}>
        <legend>1 · {identifierLabel}</legend>
        <label className="row">
          <span>{identifierLabel}</span>
          <input
            type={maskIdentifier ? "password" : "text"}
            value={identifier}
            autoComplete={identifierAutoComplete ?? "off"}
            spellCheck={false}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder={identifierPlaceholder}
          />
        </label>
        <Button
          variant="primary"
          icon={Send}
          disabled={busy || identifier === ""}
          onClick={() =>
            void run(async () => {
              const result = await requestOtp(identifier);
              setOtpResult(result);
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);
            })
          }
        >
          Request OTP (sends a {otpChannelDescription})
        </Button>
        <RawBody label="request/otp" result={otpResult} />
      </fieldset>

      <fieldset className="step" disabled={busy || txnId === ""}>
        <legend>2 · OTP</legend>
        <label className="row">
          <span>OTP</span>
          <input
            type="password"
            value={otp}
            autoComplete="one-time-code"
            onChange={(event) => setOtp(event.target.value)}
          />
        </label>
        <Button
          variant="primary"
          icon={Check}
          disabled={busy || otp === "" || txnId === ""}
          onClick={() =>
            void run(async () => {
              const result = await verifyOtp({ txnId, otp });
              setVerifyResult(result);
              // txnId for step 3: only replaced if verify's own response
              // actually carries one. Rendered raw either way; nothing
              // here assumes any flow's shape matches another's.
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);

              // singleAccount: complete login straight from verify's own
              // response -- see extractDirectSessionToken()'s/
              // extractLoggedInAddress()'s own docstrings (the logged-in
              // address is NOT always `identifier` -- the Email-OTP
              // route's own identifier is an email, not an ABHA address).
              if (singleAccount && result.data?.ok === true) {
                const direct = extractDirectSessionToken(result.data.body);
                if (direct !== null) {
                  const loggedInAddress = extractLoggedInAddress(result.data.body, identifier);
                  setSession(loggedInAddress, direct.token, loginMethod, direct.refreshToken);
                  setSessionTokenState(direct.token);
                  setSessionAddressState(loggedInAddress);
                  navigate("/home");
                }
              }
            })
          }
        >
          Verify OTP
        </Button>
        <RawBody label="verify" result={verifyResult} />
        {singleAccount && verifyResult?.data?.ok === true && extractDirectSessionToken(verifyResult.data.body) === null && (
          <p className="result result--error">
            Verify succeeded but no tokens.token found in the response — check the raw body above.
          </p>
        )}
        {!singleAccount && verifyResult !== null && (
          <p className="muted">
            The success shape here is <strong>undocumented</strong> — shown exactly as ABDM
            returned it, nothing assumed.
          </p>
        )}
      </fieldset>

      {!singleAccount && (
        <fieldset className="step" disabled={busy || !verifySucceeded}>
          <legend>3 · Pick an account</legend>
          {verifySucceeded && users.length === 0 && (
            <p className="muted">
              No linked-address list recognised in the response — check the raw body above for
              what actually came back.
            </p>
          )}
          {verifySucceeded && users.length > 0 && tToken === "" && (
            <p className="result result--error">
              No tokens.token found in verify&apos;s response — step 3 needs it as a required
              "T-token" header and cannot proceed without it. Check the raw body above.
            </p>
          )}
          {users.length > 0 && (
            <div className="user-list">
              {users.map((user) => (
                <button
                  key={user.abhaAddress}
                  type="button"
                  className="user-item"
                  disabled={busy || tToken === ""}
                  onClick={() => pickUser(user.abhaAddress)}
                >
                  <div className="user-item__address">
                    {user.abhaAddress}
                    {preferredAddress !== "" && preferredAddress === user.abhaAddress && (
                      <span className="user-item__preferred"> (preferred)</span>
                    )}
                  </div>
                  {(user.status !== null || user.kycStatus !== null) && (
                    <div className="user-item__meta">
                      {[user.status, user.kycStatus].filter((value) => value !== null).join(" · ")}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
          <RawBody label="verify/user" result={verifyUserResult} />
        </fieldset>
      )}

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
