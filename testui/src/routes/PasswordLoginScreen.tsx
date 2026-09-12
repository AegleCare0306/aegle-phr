/**
 * Password login for an ABHA address created via mobile enrollment (P1-A).
 *
 * The one login method with a real backend behind it, and the one that
 * sends no SMS -- it can be run, broken, and re-run as many times as
 * needed without touching the sandbox's OTP rate limits, unlike the three
 * "Not built yet" methods on /login which would all be OTP-based once
 * built.
 *
 * TWO steps in this screen, not three -- decided 2026-08-28 against a real
 * sandbox response, not assumed up front:
 *   1. search   -- does this address exist, and does it offer PASSWORD?
 *   2. verify   -- check the password.
 *
 * The spec's step 3 (verify/user, exchanging a txnId for the session token)
 * is SKIPPED HERE. The live run's real /login/verify success response had
 * no top-level txnId to chain into it at all (not even an empty string --
 * the field is simply absent; the token's own embedded JWT claims even
 * show an empty "txnId" inside them). But that response already carries a
 * full token/refreshToken pair under `tokens`, so nothing was missing --
 * password login's own verify call grants the session directly. This
 * screen reads the token straight out of verify's response instead of
 * calling verify/user.
 *
 * verify_user() and POST /phr/login/verify-user are NOT removed from the
 * backend over this -- ABDM describes that endpoint generically ("verify
 * the user from the list of ABHA addresses received in the response of
 * verify OTP/face authentication API"), so it may still be exactly what
 * OTP-based login methods need once built. It is simply unused by this one
 * screen, for this one method, based on what was actually observed.
 *
 * SESSION STORAGE, decided (not chosen by this component): the token goes
 * to sessionStorage via session.ts, masked wherever shown. refreshToken is
 * read out of the response only long enough to be discarded -- see
 * session.ts's own docstring for why a login token is treated differently
 * from the access key.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, LogOut, Search } from "lucide-react";

import { loginSearch, loginVerify } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { clearSession, getSessionAddress, getSessionToken, maskToken, setSession } from "../session";

/** search's documented authMethods list -- e.g. ["MOBILE_OTP", "PASSWORD", ...]. */
function extractAuthMethods(body: unknown): string[] {
  if (body !== null && typeof body === "object" && "authMethods" in body) {
    const value = (body as { authMethods: unknown }).authMethods;
    if (Array.isArray(value) && value.every((item) => typeof item === "string")) return value;
  }
  return [];
}

/**
 * Reads verify's session token out of `tokens.token`, wherever it actually
 * ended up -- observed live at that nested path, not assumed from the
 * spec's example (which only documents the token appearing at the top
 * level of the DIFFERENT verify/user response).
 */
function extractToken(body: unknown): string {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return "";
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("token" in tokens)) return "";
  const value = (tokens as { token: unknown }).token;
  return typeof value === "string" ? value : "";
}

/** Same nested path as extractToken() -- P1-N gives session.ts a real slot for this now, see its own banner. */
function extractRefreshToken(body: unknown): string {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return "";
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("refreshToken" in tokens)) return "";
  const value = (tokens as { refreshToken: unknown }).refreshToken;
  return typeof value === "string" ? value : "";
}

export function PasswordLoginScreen(): JSX.Element {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [abhaAddress, setAbhaAddress] = useState("");
  const [password, setPassword] = useState("");

  const [searchResult, setSearchResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [verifyResult, setVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Read once at mount; setSession()/clearSession() below keep this in sync
  // with sessionStorage for the rest of this component's life.
  const [sessionToken, setSessionTokenState] = useState(() => getSessionToken());
  const [sessionAddress, setSessionAddressState] = useState(() => getSessionAddress());

  const authMethods = extractAuthMethods(searchResult?.data?.body ?? null);
  const searchSucceeded = searchResult?.data?.ok === true;
  const passwordOffered = authMethods.includes("PASSWORD");

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  if (sessionToken !== "") {
    return (
      <section className="panel">
        <PageHeader icon={Lock} title="Password login" />
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
      <PageHeader icon={Lock} title="Password login" />

      <fieldset className="step" disabled={busy}>
        <legend>1 · ABHA address</legend>
        <label className="row">
          <span>ABHA address</span>
          <input
            type="text"
            value={abhaAddress}
            autoComplete="username"
            spellCheck={false}
            onChange={(event) => setAbhaAddress(event.target.value)}
            placeholder="chordiaaayush1997@sbx"
          />
        </label>
        <Button
          variant="primary"
          icon={Search}
          disabled={busy || abhaAddress === ""}
          onClick={() =>
            void run(async () => {
              setSearchResult(await loginSearch({ abhaAddress }));
            })
          }
        >
          Search
        </Button>
        <RawBody label="search" result={searchResult} />
        {searchSucceeded && (
          <p className="muted">
            authMethods: {authMethods.length > 0 ? authMethods.join(", ") : "(none reported)"} —{" "}
            {passwordOffered ? (
              <span className="ok">PASSWORD available</span>
            ) : (
              <span className="bad">PASSWORD not offered for this address</span>
            )}
          </p>
        )}
      </fieldset>

      <fieldset className="step" disabled={busy || !passwordOffered}>
        <legend>2 · Password</legend>
        <label className="row">
          <span>Password</span>
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <Button
          variant="primary"
          icon={Lock}
          disabled={busy || password === "" || !passwordOffered}
          onClick={() =>
            void run(async () => {
              const result = await loginVerify({ abhaAddress, password });
              setVerifyResult(result);

              // Token read straight from verify's own response -- see this
              // file's header comment for why there is no step 3 here.
              // refreshToken is never read at all; it simply never enters
              // this component's memory.
              const token = extractToken(result.data?.body);
              if (result.data?.ok === true && token !== "") {
                setSession(abhaAddress, token, "password", extractRefreshToken(result.data?.body));
                setSessionTokenState(token);
                setSessionAddressState(abhaAddress);
                // Aayush's explicit request: land on the new post-login
                // page instead of this screen's own "Logged in as ..."
                // view (still there below, for the case this screen is
                // revisited while already logged in via a direct URL).
                navigate("/home");
              }
            })
          }
        >
          Verify password
        </Button>
        <RawBody label="verify" result={verifyResult} />
        {verifyResult !== null && (
          <p className="muted">
            The success shape here is <strong>undocumented</strong> — shown exactly as ABDM
            returned it, nothing assumed.
          </p>
        )}
      </fieldset>

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
