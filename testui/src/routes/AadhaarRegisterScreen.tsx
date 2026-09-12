/**
 * Real Aadhaar-based ABHA Number creation (P1-F/G/I/J) -- the PRIMARY
 * registration path. NOT PART OF THE PHR SPEC; ported from repo/server/
 * abha.py's own, already-live-tested Aadhaar enrollment (tracker case
 * M1-16). This is what "Register" means at the top level -- see App.tsx's
 * nav rename.
 *
 * FLOW (P1-I's 7-step spec, ADAPTED after two live failures corrected the
 * mechanism -- P1-J):
 *   1. Aadhaar number + mobile number -> request Aadhaar OTP.
 *   2. Verify OTP -> enrol/byAadhaar (creates the ABHA Number + a default
 *      address + demographics, all in one call).
 *   3-4. IF the typed mobile doesn't match the Aadhaar-linked one -> link
 *      it, via M1 test suite Flow 10 (repo/tools/m1_test_suite/flows/
 *      link_mobile.py) -- chains DIRECTLY off the enrollment transaction,
 *      NO session/X-token needed (SKIPPED entirely if it already matches
 *      -- see mobileMatch.ts, unchanged from P1-G).
 *   5. Email verification link -- uses enrol/byAadhaar's OWN session
 *      token from step 2 (see "EMAIL, X-TOKEN SOURCE" below), so it's
 *      reachable as soon as step 2 succeeds. No dependency on step 3-4.
 *   6. ABHA Address suggestions (P1-K) -- NOT in the M1 CLI (repo/tools/
 *      m1_test_suite has no Flow for this); ported instead from Aayush's
 *      own Postman collection ("ABHA enrolment via Aadhaar" -> "ABHA
 *      Address Suggestion API"), same txnId family as step 7. Optional:
 *      you can type a desired address directly without ever calling this.
 *   7. ABHA Address creation, via M1 test suite Flow 11 (repo/tools/
 *      m1_test_suite/flows/create_abha_address.py) -- the SAME txnId
 *      enrollment's own request/otp opened, no password, no demographics.
 *
 * STEPS 3-7 ONLY RUN FOR AN ACTUALLY-NEW ABHA NUMBER (P1-L): enrol/
 * byAadhaar's own response carries `isNew` -- confirmed by M1's own
 * enrollment.py (_print_outcome(): "isNew: false" means "ABHA already
 * existed for this Aadhaar... a normal success outcome, not an error").
 * When isNew is false, this screen switches to a DIFFERENT branch
 * entirely (see "EXISTING-ACCOUNT BRANCH" below) instead of offering
 * mobile-linking/email-linking/address-creation -- those are separate,
 * already-reachable features (address creation: AbhaAddressCreationScreen;
 * mobile/email linking: planned features elsewhere), not things to
 * re-offer to someone who already has an account, mid-registration.
 *
 * EXISTING-ACCOUNT BRANCH (P1-L): shows the ABHA card (M1's own
 * get_abha_card(), gated by X-token -- see abdm_core.profile_resources)
 * and a link to Login. No mobile-link/email-link/address-create UI here
 * at all -- deliberately narrower than the new-account branch, per
 * Aayush's explicit instruction not to duplicate functionality that
 * belongs to Login or to AbhaAddressCreationScreen.
 *
 * TWO LIVE FAILURES THAT CORRECTED THIS FLOW'S MECHANISM (P1-J):
 *
 *   MOBILE LINKING: originally built against the PHR spec's own
 *   SS3.26-SS3.27 (/phr/app/login/profile/..., requiring a session
 *   X-token) -- failed live with "Invalid X-token". Confirmed why: a
 *   fresh enrol/byAadhaar's own "session" token is transaction-scoped
 *   ("typ": "Transaction" in its own JWT payload, decoded from a real
 *   failed request), not a genuine account session -- expiresIn: 1800
 *   made it LOOK like a full session, but that heuristic was wrong.
 *   Rebuilt against M1 test suite Flow 10 instead, which never needed a
 *   session at all -- it chains off the SAME "action=enrollment"
 *   transaction family enrollment itself used.
 *
 *   MOBILE LINKING, ROUND TWO (confirmed live 2026-08-31): M1's own Flow
 *   10 code sends a BLANK txnId on the request-otp call (matching how a
 *   genuinely fresh transaction starts) -- tried that literally, ABDM
 *   rejected it with "Invalid Transaction Id" on this specific scope
 *   (["abha-enrol","mobile-verify"]), even though the exact same shared
 *   function's blank txnId was accepted moments earlier for the plain
 *   ["abha-enrol"] enrollment OTP request. Fixed by sending the ORIGINAL
 *   enrollment txnId instead of blank -- the same one steps 6-7 already
 *   reuse. See abdm_core.aadhaar_enrollment's request_mobile_link_otp()
 *   for the full reasoning.
 *
 *   ADDRESS CREATION: originally reused AbhaAddressCreationScreen's own
 *   suggestion/isExists/enrol machinery (/phr/app/enrollment/...) with
 *   this flow's own txnId -- failed live with "Transaction is not found
 *   for UUID". That machinery is for a DIFFERENT scenario (an
 *   ALREADY-EXISTING ABHA Number, verified via its own fresh
 *   ownership-verification transaction) and genuinely does not recognise
 *   a txnId from THIS transaction family, regardless of which specific
 *   UUID within it is used (an earlier attempted fix re-captured
 *   enrol/byAadhaar's own txnId instead of the original request/otp one
 *   -- same family, same rejection, wrong theory). M1's own Flow 11
 *   solves it with a single dedicated call
 *   (/enrollment/enrol/abha-address) that takes the SAME txnId directly
 *   -- no suggestion, no password, no demographics, no X-token.
 *
 * EMAIL, X-TOKEN SOURCE (SETTLED, confirmed live 2026-08-31, Aayush
 * tested directly -- corrected TWICE, ended up back at the original
 * answer): M1's own _link_email() (repo/tools/m1_test_suite/flows/
 * profile_utilities.py) needs a real X-token, and enrol/byAadhaar's OWN
 * session token (tokens.token, step 2's own response) IS accepted here
 * -- despite that token being transaction-scoped ("typ": "Transaction"
 * in its own JWT) and confirmed REJECTED by mobile-linking's own
 * endpoints. Don't re-derive "transaction-scoped" into "universally
 * invalid as an X-token" a third time -- it's endpoint-specific which
 * callers accept it, confirmed to go both ways now. extractSessionToken()
 * below reads it straight from step 2's own enrolResult.
 *
 * WRONG-OTP HANDLING (step 2): the backend's `knownFailure` field is shown
 * as a clean message when set (see aegle_phr/phr/aadhaar_enrollment.py's
 * classify_enrol_by_aadhaar_failure(), ported from the M1 test suite's own
 * confirmed signatures) -- an unrecognised failure still shows the raw
 * body below it, nothing is hidden.
 */

import { useState } from "react";
import { Check, Download, IdCard, LogIn, Mail, ScanFace, Search, Send } from "lucide-react";

import {
  createAbhaAddressFromEnrollment,
  enrolByAadhaar,
  getAbhaCard,
  getAddressSuggestionsFromEnrollment,
  requestAadhaarEnrollmentOtp,
  requestEmailVerificationLink,
  requestMobileLinkOtp,
  verifyMobileLinkOtp,
} from "../api/endpoints";
import type { AbdmPassthrough, AbhaCardResponse, ApiResult } from "../api/types";
import { extractSuggestions, withSandboxSuffix } from "../addressSuggestion";
import { RawBody } from "../components/RawBody";
import { Button, ButtonLink } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { maskedMobileLastFourMatches } from "../mobileMatch";

function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

function extractAbhaProfile(body: unknown): Record<string, unknown> | null {
  if (body === null || typeof body !== "object" || !("ABHAProfile" in body)) return null;
  const profile = (body as Record<string, unknown>).ABHAProfile;
  return profile !== null && typeof profile === "object" ? (profile as Record<string, unknown>) : null;
}

/**
 * enrol/byAadhaar's top-level `isNew` -- confirmed by M1's own
 * enrollment.py (_print_outcome()): false means "ABHA already existed
 * for this Aadhaar", a normal success outcome, not an error. null means
 * absent/unparseable -- treated as "assume new" (the more common case),
 * same as M1's own "outcome unclear" fallback.
 */
function extractIsNew(body: unknown): boolean | null {
  if (body === null || typeof body !== "object" || !("isNew" in body)) return null;
  const value = (body as Record<string, unknown>).isNew;
  return typeof value === "boolean" ? value : null;
}

/** ABHAProfile.phrAddress is documented as a LIST; ABHANumber as a fallback identifier. */
function extractPreferredAddress(profile: Record<string, unknown> | null): string {
  if (profile === null) return "";
  const phrAddress = profile.phrAddress;
  if (Array.isArray(phrAddress) && typeof phrAddress[0] === "string") return phrAddress[0];
  const abhaNumber = profile.ABHANumber;
  return typeof abhaNumber === "string" ? abhaNumber : "";
}

/**
 * enrol/byAadhaar's own session token (tokens.token) -- confirmed live
 * to be usable as email-linking's X-token, despite being transaction-
 * scoped and rejected by mobile-linking's own endpoints (see this file's
 * own banner). Falls back to a bare top-level `token` defensively.
 */
function extractSessionToken(body: unknown): string {
  if (body === null || typeof body !== "object") return "";
  const record = body as Record<string, unknown>;
  const tokens = record.tokens;
  if (tokens !== null && typeof tokens === "object" && typeof (tokens as Record<string, unknown>).token === "string") {
    return (tokens as Record<string, unknown>).token as string;
  }
  return typeof record.token === "string" ? record.token : "";
}

export function AadhaarRegisterScreen(): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [aadhaarNumber, setAadhaarNumber] = useState("");
  const [mobile, setMobile] = useState("");
  const [otp, setOtp] = useState("");
  const [txnId, setTxnId] = useState("");

  const [otpResult, setOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [enrolResult, setEnrolResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Steps 3-4: mobile linking (M1 Flow 10) -- no session needed.
  const [mobileLinkOverride, setMobileLinkOverride] = useState<string | null>(null);
  const [mobileLinkTxnId, setMobileLinkTxnId] = useState("");
  const [mobileLinkOtp, setMobileLinkOtp] = useState("");
  const [mobileLinkOtpResult, setMobileLinkOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [mobileLinkVerifyResult, setMobileLinkVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Step 5: email linking -- needs the session token step 3-4's verify returns.
  const [email, setEmail] = useState("");
  const [emailResult, setEmailResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Step 6: address suggestions (P1-K, not in the M1 CLI) -- optional.
  const [suggestResult, setSuggestResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Step 7: address creation (M1 Flow 11) -- no session needed.
  const [desiredAddress, setDesiredAddress] = useState("");
  const [addressResult, setAddressResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Existing-account branch (P1-L): isNew === false -- ABHA card + Login link only.
  const [cardResult, setCardResult] = useState<ApiResult<AbhaCardResponse> | null>(null);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const abhaProfile = extractAbhaProfile(enrolResult?.data?.body ?? null);
  const preferredAddress = extractPreferredAddress(abhaProfile);
  const enrolSucceeded = enrolResult?.data?.ok === true;
  const knownFailure = enrolResult?.data?.knownFailure ?? null;
  const isNew = extractIsNew(enrolResult?.data?.body ?? null);
  const sessionToken = extractSessionToken(enrolResult?.data?.body ?? null);

  // SKIP-WHEN-REDUNDANT (steps 3-4): true only when ABHAProfile.mobile's
  // last 4 digits match what was typed in step 1 -- see mobileMatch.ts.
  // false (differ) or null (unparseable/missing) both mean "show the
  // linking step for real", never a silent skip.
  const profileMobileMasked = abhaProfile !== null ? String(abhaProfile.mobile ?? "") : "";
  const mobileAlreadyVerified =
    profileMobileMasked !== "" && mobile !== "" && maskedMobileLastFourMatches(profileMobileMasked, mobile) === true;
  const mobileLinkValue = mobileLinkOverride ?? mobile;
  const mobileLinkVerified = mobileLinkVerifyResult?.data?.ok === true;
  const suggestions = extractSuggestions(suggestResult?.data?.body ?? null);

  return (
    <section className="panel">
      <PageHeader icon={ScanFace} title="Register (Aadhaar)" />

      <p className="notice notice--warn">
        Requesting an OTP sends a <strong>real OTP via UIDAI</strong> and counts toward ABDM&apos;s
        rate limits. Request it once. If something fails, stop and check the Console rather than
        pressing it again.
      </p>
      <p className="muted">
        No name, date of birth, gender or address fields here — Aadhaar e-KYC already has all of
        that; ABDM returns it after the OTP is verified.
      </p>

      <fieldset className="step" disabled={busy || txnId !== ""}>
        <legend>1 · Aadhaar number and mobile</legend>
        <label className="row">
          <span>Aadhaar number</span>
          <input
            type="text"
            value={aadhaarNumber}
            inputMode="numeric"
            autoComplete="off"
            onChange={(event) => setAadhaarNumber(event.target.value)}
            placeholder="12-digit Aadhaar number"
          />
        </label>
        <label className="row">
          <span>Mobile</span>
          <input
            type="text"
            value={mobile}
            inputMode="numeric"
            autoComplete="off"
            onChange={(event) => setMobile(event.target.value)}
            placeholder="10-digit mobile — sent to ABDM unencrypted, see enrol/byAadhaar's own docs"
          />
        </label>
        <Button
          variant="primary"
          icon={Send}
          disabled={busy || aadhaarNumber === "" || mobile === ""}
          onClick={() =>
            void run(async () => {
              const result = await requestAadhaarEnrollmentOtp({ aadhaarNumber });
              setOtpResult(result);
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);
            })
          }
        >
          Request OTP (sends a real OTP via UIDAI)
        </Button>
        <RawBody label="request/otp" result={otpResult} />
      </fieldset>

      <fieldset className="step" disabled={busy || txnId === "" || enrolSucceeded}>
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
              const result = await enrolByAadhaar({ txnId, otp, mobile });
              setEnrolResult(result);
              // txnId is NOT re-captured from this response -- steps 6-7
              // reuse the ORIGINAL request/otp txnId unchanged, matching
              // M1's own Flow 11 exactly. See this file's own banner.
            })
          }
        >
          Verify OTP
        </Button>
        {knownFailure !== null && knownFailure !== undefined && (
          <p className="result result--error">{knownFailure}</p>
        )}
        <RawBody label="enrol/byAadhaar" result={enrolResult} />
      </fieldset>

      {enrolSucceeded && isNew === false && (
        <div className="step">
          <p className="result">
            <span className="ok">ABHA already exists</span> for this Aadhaar
            {preferredAddress !== "" ? <> — <code>{preferredAddress}</code></> : null}
          </p>
          <p className="muted">
            This is a normal, successful outcome (confirmed via M1&apos;s own enrollment flow), not
            an error. Since an account already exists, use Login instead of continuing
            registration — mobile linking, email linking, and ABHA Address creation aren&apos;t
            offered here; they&apos;re separate actions reachable once you&apos;re logged in.
          </p>
          <Button
            size="sm"
            icon={IdCard}
            disabled={busy || sessionToken === ""}
            onClick={() => void run(async () => setCardResult(await getAbhaCard({ xToken: sessionToken })))}
          >
            Fetch ABHA card
          </Button>
          {sessionToken === "" && (
            <p className="muted">No session token found in step 2&apos;s response — can&apos;t fetch the card.</p>
          )}
          {cardResult?.data?.ok === false && (
            <p className="result result--error">
              Card fetch failed (status {cardResult.data.status}) — {cardResult.data.error ?? "see status above"}.
            </p>
          )}
          {cardResult?.data?.ok && cardResult.data.base64 !== null && (
            <div className="field field--block">
              <span className="field__label">ABHA card ({cardResult.data.contentType ?? "unknown type"})</span>
              {cardResult.data.contentType?.startsWith("image/") ? (
                <img
                  src={`data:${cardResult.data.contentType};base64,${cardResult.data.base64}`}
                  alt="ABHA card"
                  style={{ maxWidth: "100%" }}
                />
              ) : (
                <a
                  className="ui-btn ui-btn--secondary ui-btn--sm"
                  href={`data:${cardResult.data.contentType ?? "application/octet-stream"};base64,${cardResult.data.base64}`}
                  download="abha-card"
                >
                  <Download size={14} className="ui-btn__icon" aria-hidden="true" /> Download ABHA card
                </a>
              )}
            </div>
          )}
          <ButtonLink variant="primary" icon={LogIn} to="/login">Go to Login</ButtonLink>
        </div>
      )}

      {enrolSucceeded && isNew !== false && (
        <>
          {preferredAddress !== "" && (
            <p className="result">
              <span className="ok">ABHA created</span> — <code>{preferredAddress}</code>
            </p>
          )}

          <fieldset className="step" disabled={busy}>
            <legend>3-4 · Link mobile number{mobileAlreadyVerified || mobileLinkVerified ? " — done" : ""}</legend>
            {mobileAlreadyVerified ? (
              <p className="muted">
                <span className="ok">Already verified</span> via Aadhaar OTP — the mobile number
                typed during registration matches the one Aadhaar e-KYC confirmed, so no separate
                verification is needed.
              </p>
            ) : mobileLinkVerified ? (
              <p className="muted">
                <span className="ok">Linked</span> — see the raw response below.
              </p>
            ) : (
              <>
                <p className="muted">
                  {profileMobileMasked !== "" && mobile !== ""
                    ? "The typed mobile number doesn't match the Aadhaar-linked one — verify it for real, or change it below."
                    : "Couldn't confirm this mobile number is already verified — link it for real."}
                </p>
                <label className="row">
                  <span>Mobile</span>
                  <input
                    type="text"
                    value={mobileLinkValue}
                    inputMode="numeric"
                    autoComplete="off"
                    onChange={(event) => setMobileLinkOverride(event.target.value)}
                  />
                </label>
                <Button
                  size="sm"
                  icon={Send}
                  disabled={busy || mobileLinkValue === ""}
                  onClick={() =>
                    void run(async () => {
                      const result = await requestMobileLinkOtp({ txnId, mobile: mobileLinkValue });
                      setMobileLinkOtpResult(result);
                      const foundTxnId = stringField(result.data?.body, "txnId");
                      if (foundTxnId !== "") setMobileLinkTxnId(foundTxnId);
                    })
                  }
                >
                  Request OTP (sends a real SMS)
                </Button>
                <RawBody label="link-mobile/request-otp" result={mobileLinkOtpResult} />

                {mobileLinkTxnId !== "" && (
                  <>
                    <label className="row">
                      <span>OTP</span>
                      <input
                        type="password"
                        value={mobileLinkOtp}
                        autoComplete="one-time-code"
                        onChange={(event) => setMobileLinkOtp(event.target.value)}
                      />
                    </label>
                    <Button
                      size="sm"
                      icon={Check}
                      disabled={busy || mobileLinkOtp === ""}
                      onClick={() =>
                        void run(async () => {
                          setMobileLinkVerifyResult(
                            await verifyMobileLinkOtp({ txnId: mobileLinkTxnId, otp: mobileLinkOtp }),
                          );
                        })
                      }
                    >
                      Verify OTP
                    </Button>
                    <RawBody label="link-mobile/verify-otp" result={mobileLinkVerifyResult} />
                  </>
                )}
              </>
            )}
          </fieldset>

          <fieldset className="step" disabled={busy || sessionToken === ""}>
            <legend>5 · Email verification link{sessionToken === "" ? " — no session token found" : ""}</legend>
            {sessionToken === "" ? (
              <p className="muted">
                Couldn&apos;t find a session token in step 2&apos;s response (expected under
                <code>tokens.token</code>) — check the raw response above.
              </p>
            ) : (
              <p className="muted">
                Using enrol/byAadhaar&apos;s own session token from step 2 — confirmed live to work
                here despite being transaction-scoped.
              </p>
            )}
            <label className="row">
              <span>Email</span>
              <input
                type="email"
                value={email}
                autoComplete="off"
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <Button
              size="sm"
              icon={Mail}
              disabled={busy || sessionToken === "" || email === ""}
              onClick={() =>
                void run(async () => {
                  setEmailResult(await requestEmailVerificationLink({ xToken: sessionToken, email }));
                })
              }
            >
              Send verification link (sends a real email)
            </Button>
            <RawBody label="request-email-verification-link" result={emailResult} />
          </fieldset>

          <fieldset className="step" disabled={busy || txnId === ""}>
            <legend>6 · ABHA Address suggestions (optional)</legend>
            <p className="muted">
              Not part of the M1 CLI — ported from the Postman collection instead. Purely a
              convenience: skip straight to step 7 and type your own if you'd rather.
            </p>
            <Button
              size="sm"
              icon={Search}
              disabled={busy || txnId === ""}
              onClick={() =>
                void run(async () => {
                  setSuggestResult(await getAddressSuggestionsFromEnrollment({ txnId }));
                })
              }
            >
              Get suggestions
            </Button>
            {suggestions.length > 0 && (
              <div className="suggestions">
                {suggestions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`chip ${desiredAddress === item ? "chip--on" : ""}`}
                    onClick={() => setDesiredAddress(item)}
                  >
                    {withSandboxSuffix(item)}
                  </button>
                ))}
              </div>
            )}
            <RawBody label="suggestion" result={suggestResult} />
          </fieldset>

          <fieldset className="step" disabled={busy || txnId === ""}>
            <legend>7 · Create the ABHA address</legend>
            <label className="row">
              <span>Desired ABHA address</span>
              <input
                type="text"
                value={desiredAddress}
                autoComplete="off"
                onChange={(event) => setDesiredAddress(event.target.value)}
                placeholder="yourname"
              />
            </label>
            {desiredAddress !== "" && (
              <p className="muted">
                Becomes <code>{withSandboxSuffix(desiredAddress)}</code>
              </p>
            )}
            <Button
              variant="primary"
              icon={Check}
              disabled={busy || desiredAddress === "" || txnId === ""}
              onClick={() =>
                void run(async () => {
                  setAddressResult(
                    await createAbhaAddressFromEnrollment({ txnId, abhaAddress: desiredAddress, preferred: 1 }),
                  );
                })
              }
            >
              Create ABHA Address
            </Button>
            <RawBody label="create-address" result={addressResult} />
          </fieldset>
        </>
      )}

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
