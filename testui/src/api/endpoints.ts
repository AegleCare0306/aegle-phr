/**
 * One function per backend endpoint. Screens call these, never apiRequest()
 * directly and never fetch().
 */

import { apiRequest } from "./client";
import type { AbdmPassthrough, AbhaCardResponse, ApiResult, HealthResponse } from "./types";

export function getHealth(): Promise<ApiResult<HealthResponse>> {
  return apiRequest<HealthResponse>("/phr/health");
}

// --- ABHA address registration via mobile (P1-A) ---------------------------
// Every response is AbdmPassthrough: ABDM's RAW body under `body`. Three of
// the five ABDM responses in this flow are undocumented, so nothing here
// declares a shape for them -- the screen renders whatever arrived and the
// Console panel shows it in full.

export interface RequestOtpBody { mobile: string }

/** SENDS A REAL SMS. Never call this in a loop or a retry. */
export function requestEnrollmentOtp(body: RequestOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/enrollment/request-otp", { method: "POST", body });
}

export interface VerifyOtpBody { txnId: string; otp: string }

export function verifyEnrollmentOtp(body: VerifyOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/enrollment/verify-otp", { method: "POST", body });
}

export interface SuggestionsBody {
  txnId: string;
  firstName: string;
  lastName: string;
  dayOfBirth: string;
  monthOfBirth: string;
  yearOfBirth: string;
  email?: string;
}

export function getAddressSuggestions(body: SuggestionsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/enrollment/suggestions", { method: "POST", body });
}

/**
 * ABDM's isExists returns `true` when the address is TAKEN, not when it is
 * available — confirmed by experiment 2026-08-27. `taken` mirrors the raw
 * boolean under an unambiguous name.
 */
export function checkAddressExists(abhaAddress: string): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>(
    `/phr/enrollment/address-exists?abhaAddress=${encodeURIComponent(abhaAddress)}`,
  );
}

export interface EnrolBody {
  txnId: string;
  mobile: string;
  abhaAddress: string;
  password: string;
  firstName: string;
  middleName: string;
  lastName: string;
  dayOfBirth: string;
  monthOfBirth: string;
  yearOfBirth: string;
  gender: string;
  email: string;
  address: string;
  stateName: string;
  stateCode: string;
  districtName: string;
  districtCode: string;
  pinCode: string;
}

export function enrol(body: EnrolBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/enrollment/enrol", { method: "POST", body });
}

// --- Real Aadhaar-based ABHA Number creation (P1-F) -------------------------
// NOT PART OF THE PHR SPEC -- ported from repo/server/abha.py's own,
// already-live-tested Aadhaar enrollment flow (tracker case M1-16). Two
// steps, not five: no separate verify-OTP call, enrolByAadhaar submits the
// OTP and mobile together.

export interface RequestAadhaarEnrollmentOtpBody { aadhaarNumber: string }

/** SENDS A REAL OTP via UIDAI. Never call this in a loop or a retry. */
export function requestAadhaarEnrollmentOtp(
  body: RequestAadhaarEnrollmentOtpBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/aadhaar-enrollment/request-otp", { method: "POST", body });
}

export interface EnrolByAadhaarBody { txnId: string; otp: string; mobile: string }

/**
 * Confirmed expected shape (Aayush's own Postman example, 2026-08-30, still
 * to be checked against a real live run): {message, txnId, tokens: {token,
 * expiresIn: 1800, refreshToken, refreshExpiresIn}, ABHAProfile: {...}, isNew}.
 * `knownFailure` on the result is set to a short string ("Incorrect OTP.")
 * when the raw body matched one of the two confirmed wrong-OTP signatures --
 * see api/types.ts's own comment.
 */
export function enrolByAadhaar(body: EnrolByAadhaarBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/aadhaar-enrollment/enrol", { method: "POST", body });
}

// Registration ends here -- no password-setting follow-up. An earlier
// version of this chunk had enrolFromAadhaar/getAddressSuggestionsFromAadhaar
// here, built on a mismodeled premise (password as part of registration,
// reusing this flow's txnId against an endpoint meant for a different
// scenario) -- removed rather than fixed forward, see
// AadhaarRegisterScreen.tsx's own banner for the full correction.

// --- ABHA Address creation for an EXISTING ABHA Number (P1-H) ---------------
// Aayush's third top-level entry, distinct from Login and Signup -- see
// aegle_phr/phr/abha_address_creation.py's own banner. Two ownership-
// verification methods, both going straight to suggestion/isExists/enrol
// after verify -- no verify/user step for either (an earlier version added
// one for the mobile variant based on a step present in the Postman
// collection; removed, it isn't actually required in practice).

export interface RequestAbhaAddressCreationOtpBody { abhaNumber: string }

/** SENDS A REAL OTP via UIDAI. Never call this in a loop or a retry. */
export function requestAbhaAddressCreationOtpAadhaar(
  body: RequestAbhaAddressCreationOtpBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/abha-address/request-otp-aadhaar", { method: "POST", body });
}

/** {txnId, otp} -- reuses VerifyOtpBody's own shape, declared above for enrollment.py's flow. */
export function verifyAbhaAddressCreationOtpAadhaar(body: VerifyOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/abha-address/verify-otp-aadhaar", { method: "POST", body });
}

/** SENDS A REAL SMS. Never call this in a loop or a retry. */
export function requestAbhaAddressCreationOtpMobile(
  body: RequestAbhaAddressCreationOtpBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/abha-address/request-otp-mobile", { method: "POST", body });
}

export function verifyAbhaAddressCreationOtpMobile(body: VerifyOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/abha-address/verify-otp-mobile", { method: "POST", body });
}

// --- Mobile linking, chained off a fresh Aadhaar enrollment (P1-J) ----------
// CORRECTED: an earlier version targeted the PHR spec's own §3.26-§3.27,
// requiring a session token (xToken) -- confirmed live to fail with
// "Invalid X-token" (a fresh enrollment's own token is transaction-scoped,
// not a real session). Ported instead from M1 test suite Flow 10
// (repo/tools/m1_test_suite/flows/link_mobile.py), which chains directly
// off the enrollment transaction -- no X-token needed at all.
//
// `txnId` IS the original enrollment transaction id, NOT blank -- CORRECTED
// AGAIN, confirmed live 2026-08-31: M1's own Flow 10 literally sends a
// blank txnId here, and that got rejected live with "Invalid Transaction
// Id" on this scope. See the backend's mobile_linking.py for the full story.

export interface RequestMobileLinkOtpBody { txnId: string; mobile: string }

/** SENDS A REAL SMS. Never call this in a loop or a retry. */
export function requestMobileLinkOtp(body: RequestMobileLinkOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link-mobile/request-otp", { method: "POST", body });
}

export interface VerifyMobileLinkOtpBody { txnId: string; otp: string }

/** M1's own confirmed success shape: {message, ABHANumber, ...}. Returned raw. */
export function verifyMobileLinkOtp(body: VerifyMobileLinkOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link-mobile/verify-otp", { method: "POST", body });
}

// --- ABHA Address creation, chained off a fresh enrollment (P1-J) ----------
// M1 test suite Flow 11 (repo/tools/m1_test_suite/flows/create_abha_address.py)
// -- the SAME txnId enrol/byAadhaar's own request/otp opened. NOT the
// suggestion/isExists/enrol trio used for an existing ABHA Number (a
// different scenario, confirmed live to reject this txnId). No suggestion,
// no password, no demographics -- just the desired local part.

export interface CreateAbhaAddressFromEnrollmentBody {
  txnId: string;
  /** Bare local part, e.g. "yourname" -- ABDM assembles "yourname@sbx" itself. */
  abhaAddress: string;
  preferred?: number;
}

export function createAbhaAddressFromEnrollment(
  body: CreateAbhaAddressFromEnrollmentBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/aadhaar-enrollment/create-address", { method: "POST", body });
}

// --- ABHA Address suggestions, chained off a fresh enrollment (P1-K) -------
// NOT implemented in the M1 CLI -- ported from Aayush's own Postman
// collection instead ("ABHA enrolment via Aadhaar" -> "ABHA Address
// Suggestion API"), same txnId family as the create-address call above.

export interface GetAddressSuggestionsFromEnrollmentBody { txnId: string }

/** ABDM's own confirmed shape: {txnId, abhaAddressList: [...]} -- bare local parts, same "@sbx" caveat as every other suggestion endpoint. */
export function getAddressSuggestionsFromEnrollment(
  body: GetAddressSuggestionsFromEnrollmentBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/aadhaar-enrollment/suggestions", { method: "POST", body });
}

// --- ABHA card, for the "ABHA number already exists" branch (P1-L) --------
// Not part of the M1 CLI's own coverage gap this time -- get_abha_card()
// IS in M1, just gated behind a real login there. Confirmed live that
// enrol/byAadhaar's own session token works as the X-token here too.

export interface GetAbhaCardBody { xToken: string }

/** Response is base64 + Content-Type, not AbdmPassthrough's `body` -- see api/types.ts. */
export function getAbhaCard(body: GetAbhaCardBody): Promise<ApiResult<AbhaCardResponse>> {
  return apiRequest<AbhaCardResponse>("/phr/aadhaar-enrollment/abha-card", { method: "POST", body });
}

// --- Profile view + updates for an already logged-in user (P1-M) ----------
// Same /phr/app/login/... URL family as Login (session.ts's own
// getSessionToken()) -- see the backend's aegle_phr/phr/profile.py for the
// full story on certificate choice, header superset, and the mobile/
// email-echo hypothesis in updateProfile.

export interface GetProfileBody { xToken: string }

export function getProfile(body: GetProfileBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/get", { method: "POST", body });
}

export interface UpdateProfileBody {
  xToken: string;
  /** Echoed back UNCHANGED from Get Profile -- this screen never lets the user type into this field directly. */
  mobile: string;
  email?: string;
  firstName?: string;
  middleName?: string;
  lastName?: string;
  dayOfBirth?: string;
  monthOfBirth?: string;
  yearOfBirth?: string;
  gender?: string;
  address?: string;
  stateName?: string;
  stateCode?: string;
  districtName?: string;
  districtCode?: string;
  profilePhoto?: string;
}

export function updateProfile(body: UpdateProfileBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update", { method: "POST", body });
}

export interface RequestUpdateMobileOtpBody { xToken: string; mobile: string }

/** SENDS A REAL SMS. Never call this in a loop or a retry. */
export function requestUpdateMobileOtp(body: RequestUpdateMobileOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update-mobile/request-otp", { method: "POST", body });
}

export interface VerifyUpdateMobileOtpBody { xToken: string; txnId: string; otp: string }

/** Confirmed success shape (real saved Postman example): {txnId, message, authResult: "success", users: [{abhaAddress}]}. */
export function verifyUpdateMobileOtp(body: VerifyUpdateMobileOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update-mobile/verify-otp", { method: "POST", body });
}

export interface RequestUpdateEmailOtpBody { xToken: string; email: string }

/** SENDS A REAL EMAIL OTP. A SEPARATE flow from requestEmailVerificationLink() below -- see profile.py's own banner. */
export function requestUpdateEmailOtp(body: RequestUpdateEmailOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update-email/request-otp", { method: "POST", body });
}

export interface VerifyUpdateEmailOtpBody { xToken: string; txnId: string; otp: string }

export function verifyUpdateEmailOtp(body: VerifyUpdateEmailOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update-email/verify-otp", { method: "POST", body });
}

export interface UpdatePasswordBody { xToken: string; abhaAddress: string; password: string }

/** No old-password field -- see profile.py's update_password() docstring. */
export function updatePassword(body: UpdatePasswordBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/update-password", { method: "POST", body });
}

// --- Link/De-link ABHA Number, Switch Profile, QR/PHR card, Refresh Token
// (P1-N). See the backend's aegle_phr/phr/profile_link.py for certificate
// choice, the three different session-token headers, and the DELINK
// hypothesis (unverified live -- see that module's own banner).

export interface LinkAbhaNumberRequestOtpBody { xToken: string; abhaNumber: string }

/** SENDS A REAL OTP (SMS or Aadhaar, per route). Same body for both sub-methods -- only the route differs. */
export function requestLinkMobileOtp(body: LinkAbhaNumberRequestOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link/mobile/request-otp", { method: "POST", body });
}

export function requestLinkAadhaarOtp(body: LinkAbhaNumberRequestOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link/aadhaar/request-otp", { method: "POST", body });
}

export interface LinkAbhaNumberVerifyOtpBody { xToken: string; txnId: string; otp: string }

/** Confirmed live shape: txnId, message, authResult, users[] (lowercase abhaNumber), accounts[] (PascalCase ABHANumber), tokens. Casing quirk is real -- see profile_link.py. */
export function verifyLinkMobileOtp(body: LinkAbhaNumberVerifyOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link/mobile/verify-otp", { method: "POST", body });
}

export function verifyLinkAadhaarOtp(body: LinkAbhaNumberVerifyOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link/aadhaar/verify-otp", { method: "POST", body });
}

export interface ProcessLinkBody { xToken: string; transactionId: string; action: "LINK" | "DELINK" }

/** DELINK is an unverified hypothesis -- see profile_link.py's own banner. */
export function processLink(body: ProcessLinkBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/link/process", { method: "POST", body });
}

export interface SwitchProfileRequestBody { xToken: string }

/** Response's own tokens.token is a T-token (5-minute lifetime) for the verify step below -- NOT this session's regular X-token. */
export function requestSwitchProfile(body: SwitchProfileRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/switch/request", { method: "POST", body });
}

export interface SwitchProfileVerifyBody { tToken: string; abhaAddress: string; txnId: string }

/** Response is a BARE top-level token/expiresIn/refreshToken -- use session.ts's extractBareSessionToken(), not extractSessionToken(). */
export function verifySwitchProfile(body: SwitchProfileVerifyBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/switch/verify", { method: "POST", body });
}

export interface GetQrCodeBody { xToken: string }

/** Response is base64 + Content-Type (AbhaCardResponse's shape, reused as-is -- both are "binary response wrapped for this JSON-only API", not ABHA-card-specific). Real payload shape unconfirmed until run live -- see profile_link.py. */
export function getQrCode(body: GetQrCodeBody): Promise<ApiResult<AbhaCardResponse>> {
  return apiRequest<AbhaCardResponse>("/phr/profile/qr-code", { method: "POST", body });
}

export interface GetPhrCardBody { xToken: string }

/** NOT the ABHA card (getAbhaCard() above) -- see profile_link.py's own banner. */
export function getPhrCard(body: GetPhrCardBody): Promise<ApiResult<AbhaCardResponse>> {
  return apiRequest<AbhaCardResponse>("/phr/profile/phr-card", { method: "POST", body });
}

export interface RefreshTokenBody { rToken: string }

/** Response: {tokens: {token, expiresIn: 1800, refreshToken, refreshExpiresIn}} -- WRAPPED, use session.ts's existing extractSessionToken()... but see ProfileScreen.tsx's own note on why that function's strict gating doesn't fit this response and a local reader is used instead. */
export function refreshSessionToken(body: RefreshTokenBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/refresh-token", { method: "POST", body });
}

// --- Get All Linked Records -- HIP-Initiated Linking, spec section 9 ------
// "Already linked" care contexts -- comes BEFORE User-Initiated Linking
// (spec section 10, explicitly the LAST chunk in this project). See the
// backend's aegle_phr/phr/links.py for the SS6.12-vs-SS9.3.5 spec
// contradiction this resolves; response shape unconfirmed until a live run.

export interface GetAllLinkedRecordsBody {
  xToken: string;
  /** Defaults to -1 (all records) on the backend if omitted -- matches the one real saved Postman request over the spec's own limit=100 example. */
  limit?: number;
}

export function getAllLinkedRecords(body: GetAllLinkedRecordsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/links/get-all", { method: "POST", body });
}

// --- Consent Manager -- all 11 patient-facing consent flows (spec §6) -----
// Same X-AUTH-TOKEN convention as getAllLinkedRecords() above. See the
// backend's aegle_phr/phr/consent.py for the approve-endpoint's spec-PDF
// omission (Postman-only), its own approve-body design judgment call, and
// that none of these 11 response shapes are confirmed against a live
// capture yet.

export interface AutoApproveBody {
  xToken: string;
  hiuId: string;
  hiTypes: string[];
  purposeText: string;
  purposeCode: string;
  purposeRefUri: string;
  periodFrom: string;
  periodTo: string;
  isApplicableForAllHIPs?: boolean;
}

/** SS6.13. 202 Accepted expected, no documented response body either place. */
export function autoApprove(body: AutoApproveBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/auto-approve", { method: "POST", body });
}

export interface SetAutoApproveStateBody { xToken: string; consentId: string }

export function disableAutoApprove(body: SetAutoApproveStateBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/auto-approve/disable", { method: "POST", body });
}

export function enableAutoApprove(body: SetAutoApproveStateBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/auto-approve/enable", { method: "POST", body });
}

export interface GetAllConsentRequestsBody {
  xToken: string;
  limit?: number;
  offset?: number;
  status?: string;
}

/** SS6.16 -- the consent-request inbox. */
export function getAllConsentRequests(body: GetAllConsentRequestsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/requests/get-all", { method: "POST", body });
}

export interface GetConsentRequestDetailsBody { xToken: string; consentRequestId: string }

/** SS6.17 -- also the pre-fill source for Approve. */
export function getConsentRequestDetails(body: GetConsentRequestDetailsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/requests/get-one", { method: "POST", body });
}

export interface ConsentGrant {
  hiTypes: string[];
  hip: { id: string };
  careContexts: { patientReference: string; careContextReference: string }[];
  permission: {
    dateRange: { from: string; to: string };
    frequency: { unit: string; value: number; repeats: number };
    accessMode: string;
    dataEraseAt: string;
  };
}

export interface ApproveConsentRequestBody {
  xToken: string;
  consentRequestId: string;
  consents: ConsentGrant[];
}

/** NOT IN THE SPEC PDF -- Postman-only, see consent.py's own banner. */
export function approveConsentRequest(body: ApproveConsentRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/requests/approve", { method: "POST", body });
}

export interface DenyConsentRequestBody { xToken: string; consentRequestId: string; reason: string }

/** SS6.21. */
export function denyConsentRequest(body: DenyConsentRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/requests/deny", { method: "POST", body });
}

export interface RevokeConsentsBody { xToken: string; consentIds: string[] }

/** SS6.22 -- acts on already-GRANTED artefacts, not a pending request. */
export function revokeConsents(body: RevokeConsentsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/revoke", { method: "POST", body });
}

export interface GetConsentArtefactsByRequestBody { xToken: string; consentRequestId: string }

/** SS6.18 -- an array, since one approved-against-multiple-HIPs request produces multiple artefacts. */
export function getConsentArtefactsByRequest(body: GetConsentArtefactsByRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/artefacts/get-by-request", { method: "POST", body });
}

export interface GetConsentArtefactBody { xToken: string; consentId: string }

/** SS6.19 -- single artefact by its own ID. */
export function getConsentArtefact(body: GetConsentArtefactBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/artefacts/get-one", { method: "POST", body });
}

export interface GetAllConsentArtefactsBody {
  xToken: string;
  limit?: number;
  offset?: number;
  status?: string;
}

/** SS6.20 -- "My Active Consents". */
export function getAllConsentArtefacts(body: GetAllConsentArtefactsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/consent/artefacts/get-all", { method: "POST", body });
}

// --- Email verification link (P1-F, added by request) ----------------------
// POST-registration action, not part of enrollment -- needs an already-issued
// session token. SENDS A REAL EMAIL. Fire-and-forget: no verify/OTP step
// exists for this flow anywhere in this project's reference code.

export interface RequestEmailVerificationLinkBody { xToken: string; email: string }

export function requestEmailVerificationLink(
  body: RequestEmailVerificationLinkBody,
): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/profile/request-email-verification-link", { method: "POST", body });
}

// --- Password login for an existing ABHA address (P1-C) --------------------
// Same passthrough pattern as enrollment: ABDM's RAW body under `body`.
// /phr/login/verify's SUCCESS shape is UNDOCUMENTED -- see the backend's
// aegle_phr/phr/login.py banner. Only /phr/login/search and
// /phr/login/verify-user have a documented shape, and even those are
// returned raw rather than parsed here.

export interface LoginSearchBody { abhaAddress: string }

export function loginSearch(body: LoginSearchBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/search", { method: "POST", body });
}

export interface LoginVerifyBody { abhaAddress: string; password: string }

export function loginVerify(body: LoginVerifyBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/verify", { method: "POST", body });
}

export interface LoginVerifyUserBody { abhaAddress: string; txnId: string; tToken: string }

/**
 * Documented to return {token, expiresIn, refreshToken, refreshExpiresIn}.
 * ABDM describes this endpoint generically ("verify the user from the list
 * of ABHA addresses received in the response of verify OTP/face
 * authentication API"), so it is expected to be reused by every other login
 * method later, not password-specific -- kept as its own function for
 * that reason, same as the backend.
 *
 * `tToken` is REQUIRED — confirmed live 2026-08-28 that this endpoint 401s
 * without it regardless of the access key/Authorization. It is the SAME
 * value the caller's own verify step returned under `tokens.token`; carry
 * it forward alongside txnId, not just txnId alone.
 */
export function loginVerifyUser(body: LoginVerifyUserBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/verify-user", { method: "POST", body });
}

// --- Mobile OTP login (P1-D) -------------------------------------------
// First real caller of loginVerifyUser above: unlike password login, verify
// here doesn't already know which ABHA address it's logging into -- it
// returns every address linked to the mobile, and the picker calls
// loginVerifyUser once the tester chooses one.

export interface RequestLoginOtpBody { mobile: string }

/** SENDS A REAL SMS. Never call this in a loop or a retry. */
export function requestLoginOtp(body: RequestLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/request-otp", { method: "POST", body });
}

export interface VerifyLoginOtpBody { txnId: string; otp: string }

export function verifyLoginOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/verify-otp", { method: "POST", body });
}

// --- Five more OTP-based login methods (P1-E) -------------------------------
// Every verify call reuses VerifyLoginOtpBody -- same {txnId, otp} shape as
// mobile login's, differing only in which backend route it hits (and
// therefore which `scope` login.py sends). Every request call SENDS A REAL
// OTP over whichever channel that flow uses (SMS, email, or via UIDAI for
// Aadhaar) -- never call one in a loop or a retry.

export interface RequestAbhaNumberAadhaarOtpBody { abhaNumber: string }

export function requestAbhaNumberAadhaarOtp(body: RequestAbhaNumberAadhaarOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-number-via-aadhaar/request-otp", { method: "POST", body });
}

export function verifyAbhaNumberAadhaarOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-number-via-aadhaar/verify-otp", { method: "POST", body });
}

export interface RequestAadhaarOtpBody { aadhaarNumber: string }

export function requestAadhaarOtp(body: RequestAadhaarOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/aadhaar-number/request-otp", { method: "POST", body });
}

export function verifyAadhaarOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/aadhaar-number/verify-otp", { method: "POST", body });
}

export interface RequestAbhaNumberMobileOtpBody { abhaNumber: string }

export function requestAbhaNumberMobileOtp(body: RequestAbhaNumberMobileOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-number-via-mobile/request-otp", { method: "POST", body });
}

export function verifyAbhaNumberMobileOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-number-via-mobile/verify-otp", { method: "POST", body });
}

export interface RequestAbhaAddressMobileOtpBody { abhaAddress: string }

export function requestAbhaAddressMobileOtp(body: RequestAbhaAddressMobileOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-address-via-mobile/request-otp", { method: "POST", body });
}

export function verifyAbhaAddressMobileOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-address-via-mobile/verify-otp", { method: "POST", body });
}

/**
 * ABHA Address login via email OTP. The field is `email`, not `abhaAddress`
 * -- the spec's own request-body example contradicts its prose here; see
 * the backend's login.py:request_abha_address_email_otp() for the full
 * discrepancy. Built against the example, resolved live.
 */
export interface RequestAbhaAddressEmailOtpBody { email: string }

export function requestAbhaAddressEmailOtp(body: RequestAbhaAddressEmailOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-address-via-email/request-otp", { method: "POST", body });
}

export function verifyAbhaAddressEmailOtp(body: VerifyLoginOtpBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/login/abha-address-via-email/verify-otp", { method: "POST", body });
}

// --- Provider Directory (spec §10.3.13-15) ----------------------------------
// Three stateless, read-only GETs -- no xToken on any of these, see the
// backend's aegle_phr/phr/providers.py for the full header/host story
// (a THIRD base URL, distinct from both links.py's and consent.py's).

export interface SearchProvidersBody {
  name: string;
  /** Always -1 ("any") -- no ABDM state/district code lookup table exists in this project. */
  stateCode?: number;
  districtCode?: number;
}

/** §10.3.13 -- an array. */
export function searchProviders(body: SearchProvidersBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/providers/search", { method: "POST", body });
}

export interface GetProviderBody { providerId: string }

/** §10.3.14 -- a single object, not an array. */
export function getProvider(body: GetProviderBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/providers/get-one", { method: "POST", body });
}

/** §10.3.15 -- an array, no params at all. */
export function getGovtPrograms(): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/providers/govt-programs", { method: "POST", body: {} });
}

// --- Data Flow (spec §7) -----------------------------------------------------
// Thin wrapper over repo/'s own already-working M3 Block 2 pipeline -- see
// the backend's aegle_phr/phr/data_flow.py for the full reuse story and
// why this is a one-time, narrow exception to never touching repo/ (reads
// AND CALLS its code, never edits it). No xToken on either call -- these
// don't hit ABDM directly at all, aegle_phr's backend just polls repo/'s
// own local file-store state.

export interface RequestHealthInformationBody {
  /** The GRANTED consent ARTEFACT's own id (consentDetail.consentId) -- see ConsentScreen.tsx's own corrected extraction. */
  consentId: string;
  hipId: string;
  hiuId: string;
  dateRangeFrom: string;
  dateRangeTo: string;
}

/** §7.3.1 -- 202 Accepted expected. Body on success: {requestId}. */
export function requestHealthInformation(body: RequestHealthInformationBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/data-flow/request", { method: "POST", body });
}

/** Polls repo/'s own local correlation state. Body: {phase: "pending"|"transaction_assigned"|"complete", transactionId, careContexts}. */
export function getHealthInformationStatus(requestId: string): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>(`/phr/data-flow/status/${encodeURIComponent(requestId)}`);
}

export interface TriggerConsentFetchBody {
  consentId: string;
  hiuId: string;
}

/**
 * Manual section 6 consent fetch for a GRANTED consent -- a RECOVERY lever
 * for a notify that went missing, not the normal path.
 *
 * Two things in the previous version of this comment are now wrong and have
 * been corrected. It is no longer repo/'s fetch_consent() (P20 moved the
 * whole section 6/7 stack into this app), and "never fires for a PATRQT
 * consent" was disproven on 2026-09-23: under the locker's own
 * registration the notify -> fetch chain fired unaided 6 times out of 6.
 *
 * 202 Accepted expected, empty body on success -- the artefact still
 * arrives later on the on-fetch callback.
 */
export function triggerConsentFetch(body: TriggerConsentFetchBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/data-flow/trigger-consent-fetch", { method: "POST", body });
}

// ---------------------------------------------------------------------------
// P19 -- Health Locker. The only route by which a patient's records reach
// this app. Replaces the removed self-view endpoints (self-view-consent,
// ensure-self-view-auto-approve, discover-self-view-consents) and
// ensure-self-subscription. See aegle_phr/phr/locker_service.py's banner.
// ---------------------------------------------------------------------------

export interface LockerStatusBody {
  xToken: string;
  patientAbhaAddress: string;
}

export interface LockerStatus {
  ok: boolean;
  lockerId: string;
  lockerConfigured: boolean;
  lockerPresent: boolean;
  lockerActive: boolean;
  subscriptionUsable: boolean;
  /** The single field the opt-in screen gates on. */
  needsOptIn: boolean;
  optInState: "PENDING" | "ALLOWED" | "DECLINED" | "OPTED_OUT" | string;
  subscription: unknown;
  autoApproval: unknown;
  error: string | null;
}

/** Is this patient's locker set up and usable? Read-only -- creates nothing. */
export function getLockerStatus(body: LockerStatusBody): Promise<ApiResult<LockerStatus>> {
  return apiRequest<LockerStatus>("/phr/locker/status", { method: "POST", body });
}

export interface LockerSetupBody {
  xToken: string;
  patientAbhaAddress: string;
}

/** 8.3.18 Setup Locker -- call ONLY after the patient presses Allow. One call creates the already-granted subscription AND its consent auto-approval policy. ABDM-1151 ("already setup") comes back as ok:true with alreadySetUp:true. */
export function setupPatientLocker(body: LockerSetupBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/locker/setup", { method: "POST", body });
}

export interface LockerDeclineBody {
  patientAbhaAddress: string;
  /** true = opting out after previously allowing; false = "Not now". */
  optedOut?: boolean;
}

/** Records the patient's "Not now" / opt-out so the automation stops asking and never silently re-subscribes them. */
export function declineLocker(body: LockerDeclineBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/locker/decline", { method: "POST", body });
}

export interface LockerInitialSyncBody {
  xToken: string;
  patientAbhaAddress: string;
  force?: boolean;
}

/** One-off backfill: raises a locker consent for care contexts linked BEFORE the subscription existed (alerts only cover what is linked after). Safe to call repeatedly -- it no-ops once DONE unless force is set. */
export function runLockerInitialSync(body: LockerInitialSyncBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/locker/initial-sync", { method: "POST", body });
}

/** One care context the locker holds, with its decrypted FHIR bundle. */
export interface LockerRecord {
  careContextReference: string;
  hipId: string | null;
  consentId: string | null;
  transactionId: string | null;
  receivedAt: string | null;
  bundle: Record<string, unknown> | null;
}

export interface LockerRecords {
  lockerId: string;
  optInState: string | null;
  initialSyncState: string | null;
  count: number;
  records: LockerRecord[];
}

export interface LockerRecordsBody {
  patientAbhaAddress: string;
  /** Optional. Only used to START the one-off backfill if it has never run. */
  xToken?: string;
}

/**
 * P20 -- everything the locker currently holds for this patient, read from
 * ITS OWN storage. No ABDM round trip: a Health Locker is entitled to keep
 * the records for the life of the consent behind them, which is what makes
 * a login a database read instead of one data request per hospital.
 *
 * Sweeps lapsed consents BEFORE returning anything, so a record whose
 * retention deadline has passed can never be served even once. If the
 * one-off backfill has never run and xToken is supplied, it starts in the
 * background and `initialSyncState` comes back RUNNING -- poll for it
 * rather than blocking the login.
 */
export function getLockerRecords(body: LockerRecordsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/locker/records", { method: "POST", body });
}

export interface LockerAlertsBody {
  patientAbhaAddress: string;
  limit?: number;
}

/** This patient's locker alert log -- every LINK/DATA event and how far it got (RECEIVED -> CONSENT_REQUESTED -> CONSENT_GRANTED -> DATA_REQUESTED -> DATA_RECEIVED, or FAILED with a reason). */
export function getLockerAlerts(body: LockerAlertsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/locker/alerts", { method: "POST", body });
}

// ---------------------------------------------------------------------------
// P13 -- Subscription Flow (spec §8). See aegle_phr/phr/subscription.py's
// own module banner for the full URL/body provenance. Every field name
// below matches that module's own function signatures exactly.
// ---------------------------------------------------------------------------

export interface GetLocalSubscriptionsBody {
  patientAbhaAddress: string;
}

/** Every locally-known subscription attempt for one patient (subscription_request table) -- no live ABDM round trip. */
export function getLocalSubscriptions(body: GetLocalSubscriptionsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/get-local", { method: "POST", body });
}

export interface GetAllSubscriptionRequestsBody {
  xToken: string;
  limit?: number;
  offset?: number;
  status?: string;
}

/** 8.3.1 -- Get all subscription requests. */
export function getAllSubscriptionRequests(body: GetAllSubscriptionRequestsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/requests/get-all", { method: "POST", body });
}

export interface ApproveSubscriptionRequestBody {
  xToken: string;
  subscriptionRequestId: string;
  isApplicableForAllHIPs: boolean;
  hiTypes: string[];
  categories: string[];
  periodFrom: string;
  periodTo: string;
  purposeText?: string;
  purposeCode?: string;
  purposeRefUri?: string;
  hipId?: string;
  hipName?: string;
}

/** 8.3.4 -- Approve subscription request. */
export function approveSubscriptionRequest(body: ApproveSubscriptionRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/approve", { method: "POST", body });
}

export interface DenySubscriptionRequestBody {
  xToken: string;
  subscriptionRequestId: string;
  reason: string;
}

/** 8.3.7 -- Deny subscription request. */
export function denySubscriptionRequest(body: DenySubscriptionRequestBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/deny", { method: "POST", body });
}

export interface EditSubscriptionBody {
  xToken: string;
  approvedSubscriptionId: string;
  hiuId: string;
  isApplicableForAllHIPs: boolean;
  hiTypes: string[];
  categories: string[];
  periodFrom: string;
  periodTo: string;
  purposeText?: string;
  purposeCode?: string;
  purposeRefUri?: string;
}

/** 8.3.9 -- Edit subscription (the one PUT in this section, sent as a POST body from the frontend same as everywhere else in this harness -- client.ts's own apiRequest() always POSTs; the PUT happens server-side in subscription.py). */
export function editSubscription(body: EditSubscriptionBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/edit", { method: "POST", body });
}

export interface GetSubscriptionDetailsByRequestIdBody {
  xToken: string;
  subscriptionRequestId: string;
}

/** 8.3.13 -- Subscription details by request id. */
export function getSubscriptionDetailsByRequestId(body: GetSubscriptionDetailsByRequestIdBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/details-by-request-id", { method: "POST", body });
}

export interface GetSubscriptionDetailsBySubscriptionIdBody {
  xToken: string;
  subscriptionId: string;
}

/** 8.3.14 -- Subscription details by subscription id. */
export function getSubscriptionDetailsBySubscriptionId(body: GetSubscriptionDetailsBySubscriptionIdBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/details-by-subscription-id", { method: "POST", body });
}

export interface GetAllPatientRequestsBody {
  xToken: string;
  consentLimit?: number;
  consentOffset?: number;
  subscriptionLimit?: number;
  subscriptionOffset?: number;
  status?: string;
}

/** 8.3.15 -- combined consent+subscription listing. */
export function getAllPatientRequests(body: GetAllPatientRequestsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/patients/requests", { method: "POST", body });
}

export interface GetPatientSubscribedLockersBody {
  xToken: string;
  includeInactive?: boolean;
}

/** 8.3.16 -- Get patient's subscribed lockers. */
export function getPatientSubscribedLockers(body: GetPatientSubscribedLockersBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/lockers/get-all", { method: "POST", body });
}

export interface GetLockerDetailsBody {
  xToken: string;
  lockerId: string;
}

/** 8.3.17 -- Locker details by locker id. */
export function getLockerDetails(body: GetLockerDetailsBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/lockers/get-one", { method: "POST", body });
}

export interface SetupLockerBody {
  xToken: string;
  lockerId: string;
}

/** 8.3.18 -- Setup Locker (X-LOCKER-ID) -- see R2 in CC_PROMPT_P13_subscription_flow_full_build.md, lockerId is caller-supplied. */
export function setupLocker(body: SetupLockerBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/setup-locker", { method: "POST", body });
}

export interface SetSubscriptionStateBody {
  xToken: string;
  subscriptionId: string;
}

/** Disable subscription -- Postman-only, no spec number. */
export function disableSubscription(body: SetSubscriptionStateBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/disable", { method: "POST", body });
}

/** Enable subscription -- Postman-only, no spec number. */
export function enableSubscription(body: SetSubscriptionStateBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/subscription/enable", { method: "POST", body });
}

// --- User-Initiated Linking (spec §10.3.1-§10.3.12) -- P15 ------------------
// All three outbound calls below return a bare 202 Accepted with nothing
// useful in ABDM's own body -- the real answer arrives later via a
// callback this backend receives, correlated by the `requestId` each of
// these three hands back (see AbdmPassthrough.requestId's own docstring).
// getUilResult() is what UilLinkScreen.tsx polls with that value.

export interface UilDiscoverBody {
  xToken: string;
  hipId: string;
  abhaAddress: string;
}

/** 10.3.1 -- no side effects on ABDM beyond a lookup; free to retry. */
export function uilDiscover(body: UilDiscoverBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/uil/discover", { method: "POST", body });
}

export interface UilLinkInitBody {
  xToken: string;
  hipId: string;
  transactionId: string;
  abhaAddress: string;
  patientMatches: unknown[];
}

/** 10.3.5 -- SENDS A REAL OTP to the patient's real registered mobile, via the HIP. Only call with the user's own explicit go-ahead. */
export function uilLinkInit(body: UilLinkInitBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/uil/link-init", { method: "POST", body });
}

export interface UilLinkConfirmBody {
  xToken: string;
  hipId: string;
  abhaAddress: string;
  token: number;
  linkRefNumber: string;
}

/** 10.3.9 -- consumes the real OTP the patient just typed. */
export function uilLinkConfirm(body: UilLinkConfirmBody): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>("/phr/uil/link-confirm", { method: "POST", body });
}

/**
 * Polls one UilLinkRequest row. `body` on a successful response is either
 * `null` (nothing saved yet -- shouldn't normally happen since the row is
 * created before the outbound call returns, but not impossible under a
 * race) or the row itself: `{requestId, stage, hipId, abhaAddress, status,
 * detail, linkRefNumber, createdAt, updatedAt}`. `status` is "PENDING"
 * until the matching callback arrives, then "DISCOVERED"/"INITIATED"/
 * "CONFIRMED" (per stage) or "ERROR" -- see aegle_phr/callbacks/
 * uil_services.py for exactly which.
 */
export function getUilResult(requestId: string): Promise<ApiResult<AbdmPassthrough>> {
  return apiRequest<AbdmPassthrough>(`/phr/uil/result?requestId=${encodeURIComponent(requestId)}`);
}
