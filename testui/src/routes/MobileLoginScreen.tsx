/**
 * Mobile OTP login for an existing ABHA address (spec §3.11-3.12).
 *
 * ⚠ Step 1 sends a REAL SMS and counts toward ABDM's rate limits, same as
 * every OTP request elsewhere in this harness. Request once, verify once.
 *
 * The reason this screen exists (not just "another login method"): it is
 * the first real caller of login.verify_user(), built in P1-C but unused
 * until now. Password login already knew exactly which ABHA address it
 * was logging into; mobile login does not -- the spec says verify returns
 * every ABHA address linked to that mobile number, and the tester picks
 * one. That picker is the one piece this screen has that
 * PasswordLoginScreen didn't need.
 *
 * Being the first real caller also surfaced a real gap: verify_user()
 * turned out to need a SECOND credential beyond the usual access key /
 * gateway auth -- a "T-token" header carrying verify's own short-lived
 * transfer token (see extractTToken() below and login.py's verify_user()
 * docstring for the two wrong guesses tried before this one). This screen
 * carries that value forward alongside txnId; PasswordLoginScreen never
 * needed to, because its own verify skipped this endpoint entirely.
 *
 * Three steps:
 *   1. request-otp  -- sends the SMS.
 *   2. verify-otp   -- checks the code. SUCCESS SHAPE UNDOCUMENTED (same
 *                      gap as verify_password's); expected by the spec's
 *                      own wrong-OTP error shape to include `users` and a
 *                      `txnId`, but that is an expectation, not a fact --
 *                      rendered raw, nothing assumed. Whether a usable
 *                      txnId is actually present is exactly the kind of
 *                      thing password login's own verify got wrong.
 *   3. verify-user  -- fires once a `users[]` entry is picked, sending
 *                      that address plus BOTH txnId and tToken from step 2.
 *
 * SESSION STORAGE: identical rule to PasswordLoginScreen -- token to
 * sessionStorage via session.ts, refreshToken read out of the response
 * only long enough to be discarded. Reuses the exact same "Logged in as
 * <address>" state, not a new one.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, LogOut, Send, Smartphone } from "lucide-react";

import { requestLoginOtp, verifyLoginOtp, loginVerifyUser } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
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
 * carry profiles belonging to people other than whoever is logging in (the
 * mobile number is shared), so ONLY abhaAddress/status/kycStatus are ever
 * pulled out here. A field like fullName or abhaNumber, even if present in
 * the real payload, is never read into this structure -- the raw JSON
 * dump above this picker is the only place that data is shown, same
 * treatment the Console panel gives the access key: visible where it must
 * be for debugging, never promoted into a rendered UI control.
 */
/**
 * verify's OWN short-lived transfer token, at `tokens.token` -- CONFIRMED
 * REQUIRED for step 3, live, 2026-08-28: verify_user() 401s without it
 * regardless of address or the usual Authorization, and a second wrong
 * guess (sending this value AS Authorization) also failed. It must be
 * sent as a separate "T-token" header instead -- see
 * aegle_phr/phr/login.py's verify_user() docstring for the full story.
 * This reader mirrors PasswordLoginScreen's own extractToken(), which
 * reads the same nested path for a different reason (there, because
 * verify's response granted the FINAL session token directly; here,
 * because it grants the intermediate one this screen must carry into
 * step 3).
 */
function extractTToken(body: unknown): string {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return "";
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("token" in tokens)) return "";
  const value = (tokens as { token: unknown }).token;
  return typeof value === "string" ? value : "";
}

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

export function MobileLoginScreen(): JSX.Element {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [mobile, setMobile] = useState("");
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
      // tToken is REQUIRED by the backend now (see extractTToken's own
      // comment) -- if verify's response didn't carry one, there is
      // nothing correct to send, so this deliberately does not call the
      // endpoint with an empty string and a guaranteed 401.
      if (tToken === "") return;
      const result = await loginVerifyUser({ abhaAddress, txnId, tToken });
      setVerifyUserResult(result);
      const token = stringField(result.data?.body, "token");
      if (result.data?.ok === true && token !== "") {
        setSession(abhaAddress, token, "mobile", stringField(result.data?.body, "refreshToken"));
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
        <PageHeader icon={Smartphone} title="Mobile OTP login" />
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
      <PageHeader icon={Smartphone} title="Mobile OTP login" />

      <p className="notice notice--warn">
        Requesting an OTP sends a <strong>real SMS</strong> and counts toward ABDM&apos;s rate
        limits. Request it once. If something fails, stop and check the Console rather than
        pressing it again.
      </p>

      <fieldset className="step" disabled={busy}>
        <legend>1 · Mobile number</legend>
        <label className="row">
          <span>Mobile</span>
          <input
            type="text"
            value={mobile}
            inputMode="numeric"
            autoComplete="off"
            onChange={(event) => setMobile(event.target.value)}
            placeholder="10-digit mobile"
          />
        </label>
        <Button
          variant="primary"
          icon={Send}
          disabled={busy || mobile === ""}
          onClick={() =>
            void run(async () => {
              const result = await requestLoginOtp({ mobile });
              setOtpResult(result);
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);
            })
          }
        >
          Request OTP (sends an SMS)
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
              const result = await verifyLoginOtp({ txnId, otp });
              setVerifyResult(result);
              // txnId for step 3: only replaced if verify's own response
              // actually carries one. If it doesn't (password login's own
              // verify didn't), txnId stays whatever step 1 issued -- which
              // may or may not be what verify_user needs. Rendered raw
              // either way; nothing here assumes the spec's guess is right.
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);
            })
          }
        >
          Verify OTP
        </Button>
        <RawBody label="verify" result={verifyResult} />
        {verifyResult !== null && (
          <p className="muted">
            The success shape here is <strong>undocumented</strong> — shown exactly as ABDM
            returned it, nothing assumed.
          </p>
        )}
      </fieldset>

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
                <div className="user-item__address">{user.abhaAddress}</div>
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

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
