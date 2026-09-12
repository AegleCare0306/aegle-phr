/**
 * Profile view + updates for an already logged-in user (P1-M) -- the
 * first screen in this app whose entire purpose IS the logged-in state.
 * Every other screen manages its own local logged-in-or-not view (see
 * App.tsx's own comment on the nav having no shared signed-in state) --
 * this one just reads the same getSessionToken()/session.ts every login
 * screen already writes to, and shows a plain "log in first" message if
 * empty. Reachable only after logging in via Password/Mobile/OTP login --
 * Aadhaar-based registration does NOT write to session.ts at all (its own
 * session token is transaction-scoped, not a real login -- see
 * AadhaarRegisterScreen.tsx's own banner), so this screen is unreachable
 * from that flow specifically, by design.
 *
 * FIVE ABDM CALLS: Get Profile, Update Profile, and the mobile/email/
 * password update pairs -- see the backend's aegle_phr/phr/profile.py for
 * the full story on certificate choice (phr_certificate_url -- this is
 * the SAME /phr/app/login/... URL family as Login, not the /enrollment/...
 * family aadhaar_enrollment.py/mobile_linking.py use), the header
 * superset (Authorization + X-Token, always), and the mobile/email-echo
 * hypothesis baked into Update Profile.
 *
 * PHOTO -- CONFIRMED ABSENT, NOT FABRICATED: neither the spec's own
 * example nor a real saved Postman example for Get Profile carries a
 * photo field. This screen does NOT show one for that reason -- a
 * defensive check for `profilePhoto`/`photo` is still made below (in case
 * a live response someday differs from both references), but the common
 * case is simply no photo, rendered as a plain placeholder note rather
 * than guessed at or left confusingly blank.
 *
 * KYC BADGE: rendered from whatever `kycStatus` string ABDM actually
 * returns, not hardcoded to only "VERIFIED"/"PENDING" -- see
 * kycBadgeClass()/kycBadgeLabel() below.
 *
 * eKYC-LOCK RULE (spec SS3.42, quoted in profileEdit.ts): kycStatus ===
 * "VERIFIED" locks name/DOB/gender as display-only; anything else leaves
 * them editable. Enforced here by disabling those specific inputs -- see
 * profileEdit.ts's isFieldLocked(), verified offline without a live call.
 *
 * "UPDATE" ONLY ACTIVATES ON A REAL CHANGE (Aayush's explicit
 * instruction): hasChanges() diffs the editable fields' current values
 * against the fetched baseline -- see profileEdit.ts. DECISION: submits
 * ALL editable fields every time (not just the changed ones) -- the
 * spec's own example body for updateProfile is a full object, not a
 * partial patch, so sending a full, current snapshot (edits included)
 * matches that shape most directly; the diff check only gates WHETHER the
 * button is enabled, not WHAT gets sent.
 *
 * MOBILE/EMAIL/PASSWORD UPDATES: three small, dedicated request->verify
 * mini-flows, built inline rather than reusing OtpLoginScreen.tsx --
 * that component's shape assumes a PRE-login flow with no X-token, ending
 * in verify_user()/a NEW session grant. These three assume an EXISTING
 * X-token throughout and end in a plain success message, no new
 * session -- different enough shape that reusing OtpLoginScreen would
 * need escape hatches for parts it doesn't have, so small and dedicated
 * was chosen instead, matching this project's own precedent of not
 * force-sharing when two flows only look similar on the surface (see
 * login.py's banner on per-module helper duplication).
 *
 * P1-N ADDITIONS -- Link/De-link ABHA Number, Switch Profile, QR Code, PHR
 * Card, Refresh Token (finishes spec SS3.31-SS3.43, the last of the
 * "PHR_Profile" section P1-M didn't cover). Per Aayush's own standing
 * navigation principle (quoted in this project's P1-N task prompt: "the
 * design has to be like an app... that is a design which should be
 * inherent in all steps"), every one of these stays ON this page or
 * returns here, rather than being a separate route or a dead-end result:
 *   - Link/De-link and Refresh Session both refetch/update what's already
 *     on screen (fetchProfile() again, or a fresh setSession()) so a
 *     success is actually visible here, not just a toast to click past.
 *   - Switch Profile succeeding behaves like a fresh login -- setSession()
 *     with the new identity, then navigate("/home"), the exact same
 *     landing every login screen already uses.
 *   - QR Code / PHR Card are buttons on THIS page, not their own routes.
 * Switch Profile is gated by session.ts's own canSwitchProfile(getLoginMethod())
 * -- spec SS3.37's own rule ("if a user logs in using an ABHA Address,
 * they will not be able to switch between different users") -- the entry
 * point is hidden entirely for a session that doesn't qualify, not shown
 * and left to fail live.
 *
 * OUT OF SCOPE, FLAGGED NOT BUILT: logout (already built, App.tsx's own
 * nav). Nothing else remains from the PHR_Profile spec section after
 * this chunk.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Cake,
  Check,
  CreditCard,
  Download,
  IdCard,
  Link2,
  Lock,
  Mail,
  Pencil,
  QrCode,
  RefreshCw,
  Repeat,
  Send,
  Smartphone,
  User,
  UserRound,
  Users,
  X,
} from "lucide-react";

import {
  getPhrCard,
  getProfile,
  getQrCode,
  processLink,
  refreshSessionToken,
  requestLinkAadhaarOtp,
  requestLinkMobileOtp,
  requestSwitchProfile,
  requestUpdateEmailOtp,
  requestUpdateMobileOtp,
  updatePassword,
  updateProfile,
  verifyLinkAadhaarOtp,
  verifyLinkMobileOtp,
  verifySwitchProfile,
  verifyUpdateEmailOtp,
  verifyUpdateMobileOtp,
} from "../api/endpoints";
import type { AbhaCardResponse, AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardTitle } from "../components/ui/Card";
import { InfoRow } from "../components/ui/InfoRow";
import { PageHeader } from "../components/ui/PageHeader";
import { ProfileHeader } from "../components/ui/ProfileHeader";
import { hasChanges, isFieldLocked } from "../profileEdit";
import { canSwitchProfile, extractBareSessionToken, getLoginMethod, getRefreshToken, getSessionAddress, getSessionToken, setSession } from "../session";

function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

/** The editable demographic/address fields Update Profile's own request carries -- mobile/email/profilePhoto are handled separately (see this file's own banner). */
const EDITABLE_FIELDS = [
  "firstName",
  "middleName",
  "lastName",
  "dayOfBirth",
  "monthOfBirth",
  "yearOfBirth",
  "gender",
  "address",
  "stateName",
  "stateCode",
  "districtName",
  "districtCode",
] as const;

const FIELD_LABELS: Record<(typeof EDITABLE_FIELDS)[number], string> = {
  firstName: "First name",
  middleName: "Middle name",
  lastName: "Last name",
  dayOfBirth: "Day of birth",
  monthOfBirth: "Month of birth",
  yearOfBirth: "Year of birth",
  gender: "Gender",
  address: "Address",
  stateName: "State name",
  stateCode: "State code",
  districtName: "District name",
  districtCode: "District code",
};

function extractFields(body: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of EDITABLE_FIELDS) out[field] = stringField(body, field);
  return out;
}

interface LinkedUser {
  abhaAddress: string;
  fullName: string | null;
  status: string | null;
  kycStatus: string | null;
}

/** Switch Profile's own users[] -- real, heterogeneous data (spec SS3.37); only these four fields are ever read out, matching OtpLoginScreen's own precedent of not promoting every field from a shared-identifier list into rendered UI. */
function extractUsers(body: unknown): LinkedUser[] {
  if (body === null || typeof body !== "object" || !("users" in body)) return [];
  const value = (body as { users: unknown }).users;
  if (!Array.isArray(value)) return [];
  const users: LinkedUser[] = [];
  for (const item of value) {
    if (item === null || typeof item !== "object" || !("abhaAddress" in item)) continue;
    const address = (item as Record<string, unknown>).abhaAddress;
    if (typeof address !== "string" || address === "") continue;
    const fullName = (item as Record<string, unknown>).fullName;
    const status = (item as Record<string, unknown>).status;
    const kycStatus = (item as Record<string, unknown>).kycStatus;
    users.push({
      abhaAddress: address,
      fullName: typeof fullName === "string" ? fullName : null,
      status: typeof status === "string" ? status : null,
      kycStatus: typeof kycStatus === "string" ? kycStatus : null,
    });
  }
  return users;
}

/** Switch-Profile-Request's own T-token, at tokens.token -- a transient 5-minute grant for the verify step, NOT this session's regular X-token. See profile_link.py's own banner. */
function extractTToken(body: unknown): string {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return "";
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object" || !("token" in tokens)) return "";
  const value = (tokens as { token: unknown }).token;
  return typeof value === "string" ? value : "";
}

/**
 * Refresh Token's own response reader -- deliberately NOT session.ts's
 * extractSessionToken(), whose expiresIn>300-and-non-empty-refreshToken
 * gate exists to tell a full session apart from a transient T-token. This
 * response is already known to be a refresh grant, and the live Postman
 * capture shows refreshToken can legitimately come back as "" -- running
 * it through that stricter gate would silently treat a real, working
 * refresh as unrecognised. A local, simpler reader instead.
 */
function extractRefreshedToken(body: unknown): { token: string; refreshToken: string } | null {
  if (body === null || typeof body !== "object" || !("tokens" in body)) return null;
  const tokens = (body as { tokens: unknown }).tokens;
  if (tokens === null || typeof tokens !== "object") return null;
  const token = (tokens as Record<string, unknown>).token;
  const refreshToken = (tokens as Record<string, unknown>).refreshToken;
  if (typeof token !== "string" || token === "") return null;
  return { token, refreshToken: typeof refreshToken === "string" ? refreshToken : "" };
}

export function ProfileScreen(): JSX.Element {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [sessionToken] = useState(() => getSessionToken());
  const [sessionAddress] = useState(() => getSessionAddress());
  const [loginMethod] = useState(() => getLoginMethod());

  const [profileResult, setProfileResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [editing, setEditing] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [updateResult, setUpdateResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Update mobile mini-flow.
  const [showMobileFlow, setShowMobileFlow] = useState(false);
  const [newMobile, setNewMobile] = useState("");
  const [mobileTxnId, setMobileTxnId] = useState("");
  const [mobileOtp, setMobileOtp] = useState("");
  const [mobileOtpResult, setMobileOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [mobileVerifyResult, setMobileVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Update email mini-flow.
  const [showEmailFlow, setShowEmailFlow] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [emailTxnId, setEmailTxnId] = useState("");
  const [emailOtp, setEmailOtp] = useState("");
  const [emailOtpResult, setEmailOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [emailVerifyResult, setEmailVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Update password mini-flow -- no OTP, one call.
  const [showPasswordFlow, setShowPasswordFlow] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [passwordResult, setPasswordResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Link/De-link ABHA Number mini-flow (P1-N).
  const [showLinkFlow, setShowLinkFlow] = useState(false);
  const [linkAction, setLinkAction] = useState<"LINK" | "DELINK">("LINK");
  const [linkMethod, setLinkMethod] = useState<"mobile" | "aadhaar">("mobile");
  const [linkAbhaNumber, setLinkAbhaNumber] = useState("");
  const [linkTxnId, setLinkTxnId] = useState("");
  const [linkOtp, setLinkOtp] = useState("");
  const [linkOtpResult, setLinkOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [linkVerifyResult, setLinkVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [linkProcessResult, setLinkProcessResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // Switch Profile mini-flow (P1-N) -- entry point hidden entirely unless canSwitchProfile(loginMethod).
  const [showSwitchFlow, setShowSwitchFlow] = useState(false);
  const [switchRequestResult, setSwitchRequestResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [switchVerifyResult, setSwitchVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  // QR Code / PHR Card (P1-N).
  const [qrResult, setQrResult] = useState<ApiResult<AbhaCardResponse> | null>(null);
  const [phrCardResult, setPhrCardResult] = useState<ApiResult<AbhaCardResponse> | null>(null);

  // Refresh Session (P1-N).
  const [refreshResult, setRefreshResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const fetchProfile = async (): Promise<void> => {
    const result = await getProfile({ xToken: sessionToken });
    setProfileResult(result);
    if (result.data?.ok === true) {
      const extracted = extractFields(result.data.body);
      setFields(extracted);
      setBaseline(extracted);
    }
  };

  // One automatic fetch on load, matching App.tsx's own "so a tester
  // opening their link sees the answer without pressing anything" --
  // Get Profile is explicitly free (no OTP, no state change) to run.
  useEffect(() => {
    if (sessionToken !== "") void run(fetchProfile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (sessionToken === "") {
    return (
      <section className="panel">
        <PageHeader icon={User} title="Profile" />
        <p className="muted">Log in first (Password or Mobile/OTP login) to view your profile.</p>
      </section>
    );
  }

  const body = profileResult?.data?.body ?? null;
  const kycStatus = stringField(body, "kycStatus");
  const fullName = stringField(body, "fullName");
  const abhaNumber = stringField(body, "abhaNumber");
  const abhaAddress = stringField(body, "abhaAddress") || sessionAddress;
  const mobile = stringField(body, "mobile");
  const email = stringField(body, "email");
  const photo = stringField(body, "profilePhoto") || stringField(body, "photo");

  const canSubmitUpdate = editing && hasChanges(baseline, fields, EDITABLE_FIELDS);

  const setField = (field: string, value: string): void => setFields((prev) => ({ ...prev, [field]: value }));

  // P1-N derived values.
  const requestLinkOtp = linkMethod === "mobile" ? requestLinkMobileOtp : requestLinkAadhaarOtp;
  const verifyLinkOtp = linkMethod === "mobile" ? verifyLinkMobileOtp : verifyLinkAadhaarOtp;
  const switchUsers = extractUsers(switchRequestResult?.data?.body ?? null);
  const switchTToken = extractTToken(switchRequestResult?.data?.body ?? null);

  return (
    <section className="panel">
      <PageHeader
        icon={User}
        title="Profile"
        actions={
          <Button size="sm" icon={RefreshCw} disabled={busy} onClick={() => void run(fetchProfile)}>
            Refresh
          </Button>
        }
      />
      <RawBody label="get-profile" result={profileResult} />

      {profileResult?.data?.ok === true && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          {photo === "" && (
            <p className="muted" style={{ marginTop: 0 }}>
              No photo available — Get Profile carries no photo field for however this account
              logged in (confirmed against both the spec and a real saved example).
            </p>
          )}
          <ProfileHeader
            photoBase64={photo}
            name={fullName || abhaAddress}
            kycStatus={kycStatus}
            onSwitchAccount={canSwitchProfile(loginMethod) ? () => setShowSwitchFlow(true) : undefined}
          />

          {(fields.dayOfBirth || fields.monthOfBirth || fields.yearOfBirth || fields.gender) && (
            <div className="ui-info-split" style={{ marginTop: "var(--space-3)" }}>
              <InfoRow
                icon={Cake}
                label="Date of Birth"
                value={
                  fields.dayOfBirth && fields.monthOfBirth && fields.yearOfBirth
                    ? `${fields.dayOfBirth}-${fields.monthOfBirth}-${fields.yearOfBirth}`
                    : "—"
                }
              />
              <InfoRow icon={Users} label="Gender" value={fields.gender || "—"} />
            </div>
          )}

          <div className="ui-info-stack" style={{ marginTop: "var(--space-2)" }}>
            <InfoRow icon={IdCard} label="ABHA Number" value={abhaNumber || "—"} />
            <InfoRow icon={UserRound} label="ABHA Address" value={abhaAddress} />
          </div>

          <Button size="sm" icon={editing ? X : Pencil} disabled={busy} onClick={() => setEditing((prev) => !prev)} style={{ marginTop: "var(--space-4)" }}>
            {editing ? "Close edit" : "Edit profile"}
          </Button>

          {editing && (
            <Card as="fieldset" disabled={busy} padding="md">
              <CardTitle icon={Pencil}>Edit demographic / address details</CardTitle>
              {kycStatus === "VERIFIED" && (
                <p className="muted">
                  This account is e-KYC verified — name, date of birth and gender are locked per
                  ABDM&apos;s own rule (spec SS3.42): e-KYC users cannot have those fields updated.
                </p>
              )}
              <div className="grid">
                {EDITABLE_FIELDS.map((field) => {
                  const locked = isFieldLocked(kycStatus, field);
                  return (
                    <label className="row" key={field}>
                      <span>{FIELD_LABELS[field]}</span>
                      <input
                        type="text"
                        value={fields[field] ?? ""}
                        disabled={busy || locked}
                        autoComplete="off"
                        onChange={(event) => setField(field, event.target.value)}
                      />
                    </label>
                  );
                })}
              </div>
              <p className="muted">
                Mobile (<code>{mobile || "—"}</code>) and email (<code>{email || "—"}</code>) are shown
                for reference only — not editable here. Use "Update mobile" / "Update email" below.
              </p>
              <Button
                variant="primary"
                icon={Check}
                disabled={busy || !canSubmitUpdate}
                onClick={() =>
                  void run(async () => {
                    const result = await updateProfile({
                      xToken: sessionToken,
                      mobile,
                      email,
                      ...fields,
                    });
                    setUpdateResult(result);
                    if (result.data?.ok === true) setBaseline(fields);
                  })
                }
              >
                Update
              </Button>
              <RawBody label="update-profile" result={updateResult} />
            </Card>
          )}

          {/* --- Update mobile ------------------------------------------- */}
          <Card as="fieldset" disabled={busy} padding="md">
            <CardTitle icon={Smartphone}>Update mobile</CardTitle>
            {!showMobileFlow ? (
              <Button size="sm" icon={Smartphone} onClick={() => setShowMobileFlow(true)}>
                Update mobile
              </Button>
            ) : (
              <>
                <p className="notice notice--warn">Sends a real SMS. Request once.</p>
                <label className="row">
                  <span>New mobile</span>
                  <input
                    type="text"
                    value={newMobile}
                    inputMode="numeric"
                    autoComplete="off"
                    onChange={(event) => setNewMobile(event.target.value)}
                  />
                </label>
                <Button
                  size="sm"
                  icon={Send}
                  disabled={busy || newMobile === ""}
                  onClick={() =>
                    void run(async () => {
                      const result = await requestUpdateMobileOtp({ xToken: sessionToken, mobile: newMobile });
                      setMobileOtpResult(result);
                      const txnId = stringField(result.data?.body, "txnId");
                      if (txnId !== "") setMobileTxnId(txnId);
                    })
                  }
                >
                  Request OTP
                </Button>
                <RawBody label="update-mobile/request-otp" result={mobileOtpResult} />

                {mobileTxnId !== "" && (
                  <>
                    <label className="row">
                      <span>OTP</span>
                      <input
                        type="password"
                        value={mobileOtp}
                        autoComplete="one-time-code"
                        onChange={(event) => setMobileOtp(event.target.value)}
                      />
                    </label>
                    <Button
                      size="sm"
                      icon={Check}
                      disabled={busy || mobileOtp === ""}
                      onClick={() =>
                        void run(async () => {
                          const result = await verifyUpdateMobileOtp({ xToken: sessionToken, txnId: mobileTxnId, otp: mobileOtp });
                          setMobileVerifyResult(result);
                          if (result.data?.ok === true) void run(fetchProfile);
                        })
                      }
                    >
                      Verify OTP
                    </Button>
                    <RawBody label="update-mobile/verify-otp" result={mobileVerifyResult} />
                  </>
                )}
              </>
            )}
          </Card>

          {/* --- Update email -------------------------------------------- */}
          <Card as="fieldset" disabled={busy} padding="md">
            <CardTitle icon={Mail}>Update email</CardTitle>
            {!showEmailFlow ? (
              <Button size="sm" icon={Mail} onClick={() => setShowEmailFlow(true)}>
                Update email
              </Button>
            ) : (
              <>
                <p className="notice notice--warn">Sends a real email OTP. Request once.</p>
                <label className="row">
                  <span>New email</span>
                  <input
                    type="email"
                    value={newEmail}
                    autoComplete="off"
                    onChange={(event) => setNewEmail(event.target.value)}
                  />
                </label>
                <Button
                  size="sm"
                  icon={Send}
                  disabled={busy || newEmail === ""}
                  onClick={() =>
                    void run(async () => {
                      const result = await requestUpdateEmailOtp({ xToken: sessionToken, email: newEmail });
                      setEmailOtpResult(result);
                      const txnId = stringField(result.data?.body, "txnId");
                      if (txnId !== "") setEmailTxnId(txnId);
                    })
                  }
                >
                  Request OTP
                </Button>
                <RawBody label="update-email/request-otp" result={emailOtpResult} />

                {emailTxnId !== "" && (
                  <>
                    <label className="row">
                      <span>OTP</span>
                      <input
                        type="password"
                        value={emailOtp}
                        autoComplete="one-time-code"
                        onChange={(event) => setEmailOtp(event.target.value)}
                      />
                    </label>
                    <Button
                      size="sm"
                      icon={Check}
                      disabled={busy || emailOtp === ""}
                      onClick={() =>
                        void run(async () => {
                          const result = await verifyUpdateEmailOtp({ xToken: sessionToken, txnId: emailTxnId, otp: emailOtp });
                          setEmailVerifyResult(result);
                          if (result.data?.ok === true) void run(fetchProfile);
                        })
                      }
                    >
                      Verify OTP
                    </Button>
                    <RawBody label="update-email/verify-otp" result={emailVerifyResult} />
                  </>
                )}
              </>
            )}
          </Card>

          {/* --- Update password ------------------------------------------ */}
          <Card as="fieldset" disabled={busy} padding="md">
            <CardTitle icon={Lock}>Update password</CardTitle>
            {!showPasswordFlow ? (
              <Button size="sm" icon={Lock} onClick={() => setShowPasswordFlow(true)}>
                Update password
              </Button>
            ) : (
              <>
                <p className="muted">
                  No old-password field — ABDM checks server-side that the new password differs from
                  the old one.
                </p>
                <label className="row">
                  <span>New password</span>
                  <input
                    type="password"
                    value={newPassword}
                    autoComplete="new-password"
                    onChange={(event) => setNewPassword(event.target.value)}
                  />
                </label>
                <Button
                  size="sm"
                  icon={Check}
                  disabled={busy || newPassword === ""}
                  onClick={() =>
                    void run(async () => {
                      setPasswordResult(
                        await updatePassword({ xToken: sessionToken, abhaAddress, password: newPassword }),
                      );
                    })
                  }
                >
                  Update password
                </Button>
                <RawBody label="update-password" result={passwordResult} />
              </>
            )}
          </Card>

          {/* --- Link/De-link ABHA Number (P1-N) --------------------------- */}
          <Card as="fieldset" disabled={busy} padding="md">
            <CardTitle icon={Link2}>Link / De-link ABHA Number</CardTitle>
            {!showLinkFlow ? (
              <Button size="sm" icon={Link2} onClick={() => setShowLinkFlow(true)}>
                Link / De-link ABHA Number
              </Button>
            ) : (
              <>
                <p className="notice notice--warn">Sends a real OTP. Request once.</p>
                <p className="muted">
                  De-link is an unverified hypothesis (no working example exists anywhere in the
                  Postman collection) — if step 3 fails with anything other than a plain rejection,
                  the raw response below is the actual outcome, not a bug in this screen.
                </p>
                <div className="row">
                  <span>Action</span>
                  <button
                    type="button"
                    className={`chip ${linkAction === "LINK" ? "chip--on" : ""}`}
                    onClick={() => setLinkAction("LINK")}
                  >
                    Link
                  </button>
                  <button
                    type="button"
                    className={`chip ${linkAction === "DELINK" ? "chip--on" : ""}`}
                    onClick={() => setLinkAction("DELINK")}
                  >
                    De-link
                  </button>
                </div>
                <div className="row">
                  <span>Verify via</span>
                  <button
                    type="button"
                    className={`chip ${linkMethod === "mobile" ? "chip--on" : ""}`}
                    onClick={() => setLinkMethod("mobile")}
                  >
                    Mobile OTP
                  </button>
                  <button
                    type="button"
                    className={`chip ${linkMethod === "aadhaar" ? "chip--on" : ""}`}
                    onClick={() => setLinkMethod("aadhaar")}
                  >
                    Aadhaar OTP
                  </button>
                </div>
                <label className="row">
                  <span>ABHA Number</span>
                  <input
                    type="text"
                    value={linkAbhaNumber}
                    autoComplete="off"
                    placeholder="91-1234-5678-9012"
                    onChange={(event) => setLinkAbhaNumber(event.target.value)}
                  />
                </label>
                <Button
                  size="sm"
                  icon={Send}
                  disabled={busy || linkAbhaNumber === ""}
                  onClick={() =>
                    void run(async () => {
                      const result = await requestLinkOtp({ xToken: sessionToken, abhaNumber: linkAbhaNumber });
                      setLinkOtpResult(result);
                      const txnId = stringField(result.data?.body, "txnId");
                      if (txnId !== "") setLinkTxnId(txnId);
                    })
                  }
                >
                  Request OTP
                </Button>
                <RawBody label="link/request-otp" result={linkOtpResult} />

                {linkTxnId !== "" && (
                  <>
                    <label className="row">
                      <span>OTP</span>
                      <input
                        type="password"
                        value={linkOtp}
                        autoComplete="one-time-code"
                        onChange={(event) => setLinkOtp(event.target.value)}
                      />
                    </label>
                    <Button
                      size="sm"
                      icon={Check}
                      disabled={busy || linkOtp === ""}
                      onClick={() =>
                        void run(async () => {
                          const result = await verifyLinkOtp({ xToken: sessionToken, txnId: linkTxnId, otp: linkOtp });
                          setLinkVerifyResult(result);
                          // Re-captured from verify's own response, same
                          // pattern as every other screen in this project
                          // -- process_link's own transactionId is THIS
                          // txnId, not necessarily step 1's original one.
                          const txnId = stringField(result.data?.body, "txnId");
                          if (txnId !== "") setLinkTxnId(txnId);
                        })
                      }
                    >
                      Verify OTP
                    </Button>
                    <RawBody label="link/verify-otp" result={linkVerifyResult} />
                    {linkVerifyResult !== null && stringField(linkVerifyResult.data?.body, "authResult") === "failed" && (
                      <p className="result result--error">
                        authResult: "failed" — a wrong/expired OTP can be a 200 here, not just a
                        4xx (confirmed live). Check the raw response above.
                      </p>
                    )}
                  </>
                )}

                {linkVerifyResult?.data?.ok === true && (
                  <>
                    <Button
                      variant="primary"
                      icon={Link2}
                      disabled={busy || linkTxnId === ""}
                      onClick={() =>
                        void run(async () => {
                          const result = await processLink({ xToken: sessionToken, transactionId: linkTxnId, action: linkAction });
                          setLinkProcessResult(result);
                          // Standing navigation principle: a successful
                          // action refetches Get Profile so the change is
                          // actually visible here, not left stale.
                          if (result.data?.ok === true) void run(fetchProfile);
                        })
                      }
                    >
                      {linkAction === "LINK" ? "Link this ABHA Number" : "De-link this ABHA Number"}
                    </Button>
                    <RawBody label="link/process" result={linkProcessResult} />
                  </>
                )}
              </>
            )}
          </Card>

          {/* --- Switch Profile (P1-N) -------------------------------------
              Entry point hidden entirely (not shown-then-failing) unless
              this session qualifies -- spec SS3.37's own rule. */}
          {canSwitchProfile(loginMethod) && (
            <Card as="fieldset" disabled={busy} padding="md">
              <CardTitle icon={Repeat}>Switch Profile</CardTitle>
              {!showSwitchFlow ? (
                <Button size="sm" icon={Repeat} onClick={() => setShowSwitchFlow(true)}>
                  Switch Profile
                </Button>
              ) : (
                <>
                  <Button
                    size="sm"
                    icon={RefreshCw}
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        setSwitchRequestResult(await requestSwitchProfile({ xToken: sessionToken }));
                      })
                    }
                  >
                    List other profiles
                  </Button>
                  <RawBody label="switch/request" result={switchRequestResult} />

                  {switchRequestResult !== null && switchUsers.length === 0 && (
                    <p className="muted">
                      No linked-address list recognised in the response — check the raw body above.
                    </p>
                  )}
                  {switchUsers.length > 0 && (
                    <div className="user-list">
                      {switchUsers.map((user) => (
                        <button
                          key={user.abhaAddress}
                          type="button"
                          className="user-item"
                          disabled={busy || switchTToken === ""}
                          onClick={() =>
                            void run(async () => {
                              const result = await verifySwitchProfile({
                                tToken: switchTToken,
                                abhaAddress: user.abhaAddress,
                                txnId: stringField(switchRequestResult?.data?.body, "txnId"),
                              });
                              setSwitchVerifyResult(result);
                              const bare = extractBareSessionToken(result.data?.body);
                              if (result.data?.ok === true && bare !== null && loginMethod !== null) {
                                // Standing navigation principle: behaves
                                // exactly like finishing a login screen --
                                // new session, land on /home, not a
                                // dead-end confirmation here.
                                setSession(user.abhaAddress, bare.token, loginMethod, bare.refreshToken);
                                navigate("/home");
                              }
                            })
                          }
                        >
                          <div className="user-item__address">{user.abhaAddress}</div>
                          {(user.fullName !== null || user.status !== null || user.kycStatus !== null) && (
                            <div className="user-item__meta">
                              {[user.fullName, user.status, user.kycStatus].filter((v) => v !== null).join(" · ")}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                  <RawBody label="switch/verify" result={switchVerifyResult} />
                </>
              )}
            </Card>
          )}

          {/* --- QR Code / PHR Card (P1-N) ---------------------------------
              Reachable from the profile page itself, per Aayush's own
              standing navigation instruction -- not a separate route.
              Restyled (P14) to the reference app's QR-card + button-
              hierarchy look (design_reference/05_profile.png) -- "Get QR
              Code" as the one solid primary action (closest existing
              equivalent to that reference's "Scan & Share": this app has
              no separate scan flow, see the P14 verification report),
              "Get PHR Card" as a secondary outline action. No new calls or
              behavior, same two buttons as before. */}
          <Card padding="md" className="ui-card--flush">
            <CardBody>
              <CardTitle icon={QrCode}>QR Code / PHR Card</CardTitle>
              <p className="muted">
                Real payload shape unconfirmed until run live (spec labels both "202 Accepted" with
                only placeholder saved examples) — renders as an image if the response says so,
                otherwise offers a download.
              </p>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => void run(async () => setQrResult(await getQrCode({ xToken: sessionToken })))}
                  style={{ flex: 1 }}
                >
                  Get QR Code
                </Button>
                <Button
                  variant="secondary"
                  icon={CreditCard}
                  disabled={busy}
                  onClick={() => void run(async () => setPhrCardResult(await getPhrCard({ xToken: sessionToken })))}
                  style={{ flex: 1 }}
                >
                  Get PHR Card
                </Button>
              </div>

            {[
              { label: "QR code", result: qrResult, filename: "qr-code" },
              { label: "PHR card", result: phrCardResult, filename: "phr-card" },
            ].map(({ label, result, filename }) =>
              result?.data?.ok === true && result.data.base64 !== null ? (
                <div className="field field--block" key={label}>
                  <span className="field__label">
                    {label} ({result.data.contentType ?? "unknown type"})
                  </span>
                  {result.data.contentType?.startsWith("image/") ? (
                    <img
                      src={`data:${result.data.contentType};base64,${result.data.base64}`}
                      alt={label}
                      style={{ maxWidth: 200 }}
                    />
                  ) : (
                    <a
                      className="ui-btn ui-btn--secondary ui-btn--sm"
                      href={`data:${result.data.contentType ?? "application/octet-stream"};base64,${result.data.base64}`}
                      download={filename}
                    >
                      <Download size={14} className="ui-btn__icon" aria-hidden="true" /> Download {label}
                    </a>
                  )}
                </div>
              ) : null,
            )}
              {qrResult?.data?.ok === false && (
                <p className="result result--error">QR code fetch failed (status {qrResult.data.status}).</p>
              )}
              {phrCardResult?.data?.ok === false && (
                <p className="result result--error">PHR card fetch failed (status {phrCardResult.data.status}).</p>
              )}
            </CardBody>
          </Card>

          {/* --- Refresh Session (P1-N) ------------------------------------ */}
          <Card as="fieldset" disabled={busy} padding="md">
            <CardTitle icon={RefreshCw}>Refresh Session</CardTitle>
            <p className="muted">
              Uses the refresh token stored at login. Whether ABDM actually rotates it or always
              returns it empty is unconfirmed — either way, this screen updates in place, no
              re-login needed.
            </p>
            <Button
              size="sm"
              icon={RefreshCw}
              disabled={busy || getRefreshToken() === ""}
              onClick={() =>
                void run(async () => {
                  const result = await refreshSessionToken({ rToken: getRefreshToken() });
                  setRefreshResult(result);
                  const refreshed = extractRefreshedToken(result.data?.body);
                  if (result.data?.ok === true && refreshed !== null && loginMethod !== null) {
                    setSession(sessionAddress, refreshed.token, loginMethod, refreshed.refreshToken);
                  }
                })
              }
            >
              Refresh Session
            </Button>
            {getRefreshToken() === "" && (
              <p className="muted">No refresh token stored for this session — log in again to get one.</p>
            )}
            <RawBody label="refresh-token" result={refreshResult} />
          </Card>
        </div>
      )}

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
