"""
The PHR app's routes, as a router -- not as a FastAPI application.

This is the seam that makes the PHR mountable. A host application (the
existing ABDM backend, eventually) gets working PHR endpoints with:

    bootstrap(settings)
    app.include_router(build_router(settings))

Everything here obeys the mountability rules:
  - no module-level side effects
  - no global state; a fresh router per build_router() call
  - no @app.on_event handlers -- startup work belongs in bootstrap()
  - every path fully qualified (/api/v3/... or /phr/...), so nothing
    depends on being mounted under a particular prefix
  - every handler a plain `def` (see aegle_phr/db.py for why)
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from abdm_core.http import generate_request_id

from aegle_phr.access import api_key_dependency
from aegle_phr.callbacks.router import build_callback_router
from aegle_phr.db import check_connection
from aegle_phr.phr import locker_hiu_repository, locker_repository, locker_service, retention
from aegle_phr.phr import abha_address_creation, abha_card, aadhaar_enrollment, consent, data_flow, email_verification, enrollment, links, login, mobile_linking, profile, profile_link, providers, subscription, uil
from aegle_phr.phr.subscription_repository import get_all_for_patient as get_all_local_subscriptions_for_patient
from aegle_phr.phr.uil_repository import get_by_request_id as get_uil_request_by_id, save_new_request as save_new_uil_request, update_by_request_id as update_uil_request
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.phr.schemas import (
    ApproveConsentRequestBody,
    AutoApproveBody,
    CreateAbhaAddressFromEnrollmentBody,
    DenyConsentRequestBody,
    EnrolBody,
    EnrolByAadhaarBody,
    GetAbhaCardBody,
    GetAddressSuggestionsFromEnrollmentBody,
    GetAllConsentArtefactsBody,
    GetAllConsentRequestsBody,
    GetAllLinkedRecordsBody,
    GetConsentArtefactBody,
    GetConsentArtefactsByRequestBody,
    GetConsentRequestDetailsBody,
    GetGovtProgramsBody,
    GetPhrCardBody,
    GetProfileBody,
    GetProviderBody,
    GetQrCodeBody,
    LinkAbhaNumberRequestOtpBody,
    LinkAbhaNumberVerifyOtpBody,
    ProcessLinkBody,
    RefreshTokenBody,
    RequestAadhaarEnrollmentOtpBody,
    RequestAadhaarOtpBody,
    RequestAbhaAddressCreationAadhaarOtpBody,
    RequestAbhaAddressCreationMobileOtpBody,
    RequestAbhaAddressEmailOtpBody,
    RequestAbhaAddressMobileOtpBody,
    RequestAbhaNumberAadhaarOtpBody,
    RequestAbhaNumberMobileOtpBody,
    RequestEmailVerificationLinkBody,
    RequestLoginOtpBody,
    RequestMobileLinkOtpBody,
    RequestOtpBody,
    RequestHealthInformationBody,
    RequestUpdateEmailOtpBody,
    TriggerConsentFetchBody,
    GetAllSubscriptionRequestsBody,
    ApproveSubscriptionRequestBody,
    DenySubscriptionRequestBody,
    EditSubscriptionBody,
    GetSubscriptionDetailsByRequestIdBody,
    GetSubscriptionDetailsBySubscriptionIdBody,
    GetAllPatientRequestsBody,
    GetPatientSubscribedLockersBody,
    GetLockerDetailsBody,
    SetupLockerBody,
    LockerStatusBody,
    LockerSetupBody,
    LockerDeclineBody,
    LockerInitialSyncBody,
    LockerAlertsBody,
    LockerRecordsBody,
    SetSubscriptionStateBody,
    GetLocalSubscriptionsBody,
    RequestUpdateMobileOtpBody,
    RevokeConsentsBody,
    SearchProvidersBody,
    SearchUserBody,
    SetAutoApproveStateBody,
    SuggestionsBody,
    SwitchProfileRequestBody,
    SwitchProfileVerifyBody,
    UilDiscoverBody,
    UilLinkConfirmBody,
    UilLinkInitBody,
    UpdatePasswordBody,
    UpdateProfileBody,
    VerifyLoginOtpBody,
    VerifyLoginUserBody,
    VerifyMobileLinkOtpBody,
    VerifyOtpBody,
    VerifyPasswordBody,
    VerifyUpdateEmailOtpBody,
    VerifyUpdateMobileOtpBody,
)
from aegle_phr.settings import Settings


def _passthrough(result: AbdmResult) -> dict:
    """
    Hands ABDM's raw body back to the UI, untouched.

    Deliberately does NOT reshape or validate: three of the five responses
    in this flow are undocumented (see enrollment.py's banner), so the UI
    and the Console panel must see exactly what arrived. `ok` is derived
    from the status code only.
    """
    return {
        "ok": result.ok,
        "status": result.status_code,
        "body": result.body,
        "error": result.error,
    }


def _record_uil_failure(request_id: str, payload: dict) -> dict:
    """
    Marks a UIL row FAILED when its outbound call was never accepted.

    All three UIL routes save a PENDING row BEFORE calling ABDM, so that a
    callback arriving before our own HTTP response still has something to
    correlate against. The gap was the other branch: when ABDM rejects the
    call outright there will never BE a callback, and nothing moved the row
    off PENDING -- leaving it permanently indistinguishable from one
    genuinely in flight.

    Confirmed live 2026-09-23: four rejected discovers from 2026-09-05 were
    still sitting PENDING eighteen days later, alongside a fresh one
    rejected as a duplicate. Returns the payload unchanged so callers can
    `return _record_uil_failure(...)` directly.
    """
    if payload.get("ok") is not True:
        update_uil_request(request_id, status="FAILED", detail={"response": payload.get("body")})
    return payload


def _passthrough_aadhaar_enrol(result: aadhaar_enrollment.AbdmResult) -> dict:
    """
    Same shape as _passthrough(), plus `knownFailure` -- mirrors how
    /phr/enrollment/address-exists already adds its own `taken` field
    alongside the raw passthrough. None on success or an unrecognised
    failure; a short string ("Incorrect OTP.") only when
    classify_enrol_by_aadhaar_failure() matched one of the two confirmed
    wrong-OTP signatures -- see aegle_phr/phr/aadhaar_enrollment.py.
    """
    payload = _passthrough(result)  # type: ignore[arg-type]  -- structurally identical AbdmResult
    payload["knownFailure"] = result.known_failure
    return payload


def build_app_api_router(settings: Settings) -> APIRouter:
    """
    Routes the test UI calls. Gated by the shared X-Aegle-Key at ROUTER
    level, so any route added here inherits the gate by construction.
    """
    router = APIRouter(dependencies=[Depends(api_key_dependency(settings))])

    @router.get("/phr/health", summary="PHR health check")
    def health() -> dict:
        # check_connection() never raises: a down database reports
        # "database": false with a 200, rather than turning the health
        # endpoint itself into a 500. See db.check_connection().
        return {
            "status": "healthy",
            "database": check_connection(),
        }

    # -- ABHA address registration via mobile number (P1-A) ----------------
    # Five flat steps; the UI holds the txnId and passes it back each time.
    # Every one of these inherits the X-Aegle-Key gate from the router.

    @router.post("/phr/enrollment/request-otp", summary="Step 1 — request enrollment OTP (SENDS A REAL SMS)")
    def request_otp(body: RequestOtpBody) -> dict:
        return _passthrough(enrollment.request_otp(settings, body.mobile))

    @router.post("/phr/enrollment/verify-otp", summary="Step 2 — verify enrollment OTP")
    def verify_otp(body: VerifyOtpBody) -> dict:
        return _passthrough(enrollment.verify_otp(settings, body.txnId, body.otp))

    @router.post("/phr/enrollment/suggestions", summary="Step 3 — ABHA address suggestions")
    def suggestions(body: SuggestionsBody) -> dict:
        return _passthrough(enrollment.address_suggestions(
            settings,
            txn_id=body.txnId,
            first_name=body.firstName,
            last_name=body.lastName,
            day_of_birth=body.dayOfBirth,
            month_of_birth=body.monthOfBirth,
            year_of_birth=body.yearOfBirth,
            email=body.email,
        ))

    @router.get("/phr/enrollment/address-exists", summary="Step 4 — does this ABHA address already exist? (true = TAKEN)")
    def address_exists(abhaAddress: str = Query(min_length=1)) -> dict:
        # ABDM's isExists returns true when the address is TAKEN -- the
        # opposite of "available". See enrollment.address_exists(). `taken`
        # is added alongside the raw body so no caller has to remember the
        # polarity; `body` is still ABDM's untouched boolean.
        result = enrollment.address_exists(settings, abhaAddress)
        payload = _passthrough(result)
        payload["taken"] = result.body if isinstance(result.body, bool) else None
        return payload

    @router.post("/phr/enrollment/enrol", summary="Step 5 — create the ABHA address")
    def enrol(body: EnrolBody) -> dict:
        return _passthrough(enrollment.enrol(
            settings,
            txn_id=body.txnId,
            mobile=body.mobile,
            abha_address=body.abhaAddress,
            password=body.password,
            phr_details=body.phr_details(),
        ))

    # -- Real Aadhaar-based ABHA Number creation (P1-F) ----------------------
    # NOT PART OF THE PHR SPEC -- ported from repo/server/abha.py's
    # request_otp(action="enrollment")/enroll_by_aadhaar(), already tested
    # live against the sandbox (tracker case M1-16). Two steps, not five:
    # no separate verify-OTP call, enrol-by-aadhaar submits the OTP and
    # mobile together. See aegle_phr/phr/aadhaar_enrollment.py's own banner
    # for why this needs a DIFFERENT certificate than every other call here.

    @router.post("/phr/aadhaar-enrollment/request-otp", summary="Real Aadhaar enrollment step 1 — SENDS A REAL OTP via UIDAI")
    def aadhaar_enrollment_request_otp(body: RequestAadhaarEnrollmentOtpBody) -> dict:
        return _passthrough(aadhaar_enrollment.request_otp(settings, body.aadhaarNumber))  # type: ignore[arg-type]

    @router.post("/phr/aadhaar-enrollment/enrol", summary="Real Aadhaar enrollment step 2 — OTP + mobile together, no separate verify")
    def aadhaar_enrollment_enrol(body: EnrolByAadhaarBody) -> dict:
        return _passthrough_aadhaar_enrol(
            aadhaar_enrollment.enrol_by_aadhaar(settings, body.txnId, body.otp, body.mobile)
        )

    # Registration ends at enrol_by_aadhaar above -- no password-setting
    # follow-up route here. An earlier version of this chunk had
    # enrol-from-aadhaar/suggestions-from-aadhaar, built on a mismodeled
    # premise (password as part of registration, reusing this flow's own
    # txnId against enrollment.enrol() -- an endpoint whose real purpose,
    # confirmed against Aayush's own Postman collection, is creating an
    # ABHA ADDRESS for an ALREADY-EXISTING ABHA Number via a fresh
    # ownership-verification transaction, a different scenario this chunk
    # does not build). Removed rather than fixed forward -- see
    # aegle_phr/phr/aadhaar_enrollment.py's module banner for the full
    # correction, and testui's AadhaarRegisterScreen.tsx for the UI side.

    # -- Mobile linking, chained off a fresh Aadhaar enrollment (P1-J) --------
    # CORRECTED: an earlier version targeted the PHR spec's own SS3.26-3.27
    # (requiring a session X-token) -- confirmed live to fail with "Invalid
    # X-token" (a fresh enrollment's own token is transaction-scoped, not a
    # real session). Ported instead from M1 test suite Flow 10, which
    # chains directly off the enrollment transaction -- no X-token needed.
    # AadhaarRegisterScreen.tsx decides whether to show this step at all
    # (skipped when the typed mobile already matches the Aadhaar-linked one).

    @router.post("/phr/profile/link-mobile/request-otp", summary="Mobile linking step 1 — SENDS A REAL SMS, chains off a fresh enrollment")
    def link_mobile_request_otp(body: RequestMobileLinkOtpBody) -> dict:
        return _passthrough(mobile_linking.request_otp(settings, body.txnId, body.mobile))  # type: ignore[arg-type]

    @router.post("/phr/profile/link-mobile/verify-otp", summary="Mobile linking step 2 — verify OTP")
    def link_mobile_verify_otp(body: VerifyMobileLinkOtpBody) -> dict:
        return _passthrough(mobile_linking.verify_otp(settings, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/aadhaar-enrollment/create-address", summary="ABHA Address creation, chained off a fresh enrollment (same txnId, no suggestion/password needed)")
    def aadhaar_enrollment_create_address(body: CreateAbhaAddressFromEnrollmentBody) -> dict:
        return _passthrough(aadhaar_enrollment.create_abha_address(settings, body.txnId, body.abhaAddress, body.preferred))  # type: ignore[arg-type]

    @router.post("/phr/aadhaar-enrollment/suggestions", summary="ABHA Address suggestions, chained off a fresh enrollment (NOT in the M1 CLI -- see aadhaar_enrollment.py banner)")
    def aadhaar_enrollment_suggestions(body: GetAddressSuggestionsFromEnrollmentBody) -> dict:
        return _passthrough(aadhaar_enrollment.get_address_suggestions(settings, body.txnId))  # type: ignore[arg-type]

    # -- ABHA card, for the "ABHA number already exists" branch (P1-L) -------
    # Not the standard AbdmPassthrough shape -- the card is binary, so the
    # response carries a base64 body + its Content-Type instead of a JSON
    # `body`. See aegle_phr/phr/abha_card.py's own banner.

    @router.post("/phr/aadhaar-enrollment/abha-card", summary="Fetch the ABHA card (X-token = enrol/byAadhaar's own session token)")
    def aadhaar_enrollment_abha_card(body: GetAbhaCardBody) -> dict:
        result = abha_card.get_abha_card(settings, body.xToken)
        return {
            "ok": result.ok,
            "status": result.status_code,
            "contentType": result.content_type,
            "base64": result.base64_body,
            "error": result.error,
        }

    # -- Profile view + updates for an already logged-in user (P1-M) ---------
    # See aegle_phr/phr/profile.py's own banner for certificate choice,
    # header superset, and the mobile/email-echo hypothesis in updateProfile.
    # Route names deliberately don't collide with the already-claimed
    # /phr/profile/link-mobile/* (that's the enrollment-chained flow, a
    # different problem -- left alone).

    @router.post("/phr/profile/get", summary="Get Profile (SS3.39)")
    def profile_get(body: GetProfileBody) -> dict:
        return _passthrough(profile.get_profile(settings, body.xToken))  # type: ignore[arg-type]

    @router.post("/phr/profile/update", summary="Update Profile (SS3.42) -- mobile/email echoed unchanged, not editable here")
    def profile_update(body: UpdateProfileBody) -> dict:
        return _passthrough(profile.update_profile(settings, body.xToken, body.mobile, body.email, body.fields()))  # type: ignore[arg-type]

    @router.post("/phr/profile/update-mobile/request-otp", summary="Update Mobile step 1 (SS3.26) -- SENDS A REAL SMS")
    def profile_update_mobile_request_otp(body: RequestUpdateMobileOtpBody) -> dict:
        return _passthrough(profile.request_update_mobile_otp(settings, body.xToken, body.mobile))  # type: ignore[arg-type]

    @router.post("/phr/profile/update-mobile/verify-otp", summary="Update Mobile step 2 (SS3.27)")
    def profile_update_mobile_verify_otp(body: VerifyUpdateMobileOtpBody) -> dict:
        return _passthrough(profile.verify_update_mobile_otp(settings, body.xToken, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/profile/update-email/request-otp", summary="Update Email step 1 (SS3.28) -- SENDS A REAL EMAIL OTP")
    def profile_update_email_request_otp(body: RequestUpdateEmailOtpBody) -> dict:
        return _passthrough(profile.request_update_email_otp(settings, body.xToken, body.email))  # type: ignore[arg-type]

    @router.post("/phr/profile/update-email/verify-otp", summary="Update Email step 2 (SS3.29)")
    def profile_update_email_verify_otp(body: VerifyUpdateEmailOtpBody) -> dict:
        return _passthrough(profile.verify_update_email_otp(settings, body.xToken, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/profile/update-password", summary="Update Password (SS3.30) -- no old-password field, see profile.py")
    def profile_update_password(body: UpdatePasswordBody) -> dict:
        return _passthrough(profile.update_password(settings, body.xToken, body.abhaAddress, body.password))  # type: ignore[arg-type]

    # -- Link/De-link ABHA Number, Switch Profile, QR/PHR card, Refresh
    # Token (P1-N) -- finishes the PHR spec's own "PHR_Profile" section.
    # See aegle_phr/phr/profile_link.py's own banner for certificate
    # choice, the three different session-token headers (X-Token/T-token/
    # R-token), and the DELINK hypothesis.

    @router.post("/phr/profile/link/mobile/request-otp", summary="Link/De-link ABHA Number step 1, Mobile OTP (SS3.31/3.34) -- SENDS A REAL SMS")
    def profile_link_mobile_request_otp(body: LinkAbhaNumberRequestOtpBody) -> dict:
        return _passthrough(profile_link.request_link_mobile_otp(settings, body.xToken, body.abhaNumber))  # type: ignore[arg-type]

    @router.post("/phr/profile/link/mobile/verify-otp", summary="Link/De-link ABHA Number step 2, Mobile OTP (SS3.32/3.35)")
    def profile_link_mobile_verify_otp(body: LinkAbhaNumberVerifyOtpBody) -> dict:
        return _passthrough(profile_link.verify_link_mobile_otp(settings, body.xToken, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/profile/link/aadhaar/request-otp", summary="Link/De-link ABHA Number step 1, Aadhaar OTP (SS3.31/3.34) -- SENDS A REAL OTP via UIDAI")
    def profile_link_aadhaar_request_otp(body: LinkAbhaNumberRequestOtpBody) -> dict:
        return _passthrough(profile_link.request_link_aadhaar_otp(settings, body.xToken, body.abhaNumber))  # type: ignore[arg-type]

    @router.post("/phr/profile/link/aadhaar/verify-otp", summary="Link/De-link ABHA Number step 2, Aadhaar OTP (SS3.32/3.35)")
    def profile_link_aadhaar_verify_otp(body: LinkAbhaNumberVerifyOtpBody) -> dict:
        return _passthrough(profile_link.verify_link_aadhaar_otp(settings, body.xToken, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/profile/link/process", summary="Link/De-link ABHA Number step 3 (SS3.33/3.36) -- DELINK is an unverified hypothesis, see profile_link.py")
    def profile_link_process(body: ProcessLinkBody) -> dict:
        return _passthrough(profile_link.process_link(settings, body.xToken, body.transactionId, body.action))  # type: ignore[arg-type]

    @router.post("/phr/profile/switch/request", summary="Switch Profile step 1 (SS3.37)")
    def profile_switch_request(body: SwitchProfileRequestBody) -> dict:
        return _passthrough(profile_link.request_switch_profile(settings, body.xToken))  # type: ignore[arg-type]

    @router.post("/phr/profile/switch/verify", summary="Switch Profile step 2 (SS3.38) -- T-token, not X-token; bare top-level token in the response")
    def profile_switch_verify(body: SwitchProfileVerifyBody) -> dict:
        return _passthrough(profile_link.verify_switch_profile(settings, body.tToken, body.abhaAddress, body.txnId))  # type: ignore[arg-type]

    # QR Code / PHR Card: NOT the standard AbdmPassthrough shape -- both are
    # binary (spec: 202 Accepted, real Content-Type unconfirmed until run
    # live), so the response carries a base64 body + Content-Type instead
    # of a JSON `body`, same convention as /phr/aadhaar-enrollment/abha-card.

    @router.post("/phr/profile/qr-code", summary="Get QR Code (SS3.40) -- real payload shape unconfirmed, see profile_link.py")
    def profile_qr_code(body: GetQrCodeBody) -> dict:
        result = profile_link.get_qr_code(settings, body.xToken)
        return {
            "ok": result.ok,
            "status": result.status_code,
            "contentType": result.content_type,
            "base64": result.base64_body,
            "error": result.error,
        }

    @router.post("/phr/profile/phr-card", summary="Get PHR Card (SS3.41) -- NOT the ABHA card, see profile_link.py")
    def profile_phr_card(body: GetPhrCardBody) -> dict:
        result = profile_link.get_phr_card(settings, body.xToken)
        return {
            "ok": result.ok,
            "status": result.status_code,
            "contentType": result.content_type,
            "base64": result.base64_body,
            "error": result.error,
        }

    @router.post("/phr/profile/refresh-token", summary="Generate Refresh Token (SS3.43) -- R-token header, not X-token")
    def profile_refresh_token(body: RefreshTokenBody) -> dict:
        return _passthrough(profile_link.refresh_token(settings, body.rToken))  # type: ignore[arg-type]

    # -- Get All Linked Records -- HIP-Initiated Linking, spec section 9 -----
    # "Already linked" care contexts for the logged-in user's account --
    # comes BEFORE User-Initiated Linking (spec section 10, explicitly the
    # LAST chunk in this project) per Aayush's own instruction. See
    # aegle_phr/phr/links.py's own banner for the SS6.12-vs-SS9.3.5 spec
    # contradiction this resolves; response shape unconfirmed until a live
    # run captures it.

    @router.post("/phr/links/get-all", summary="Get All Linked Records (spec SS9.3.5, trusted over the contradicting SS6.12 -- see links.py)")
    def links_get_all(body: GetAllLinkedRecordsBody) -> dict:
        return _passthrough(links.get_all_linked_records(settings, body.xToken, body.limit))  # type: ignore[arg-type]

    # -- Consent Manager -- all 11 patient-facing consent flows (spec §6) ----
    # Same host/header family as links.py above (X-AUTH-TOKEN, not
    # X-Token). See aegle_phr/phr/consent.py's own banner for the
    # approve-endpoint's spec-PDF omission (Postman-only), its own
    # approve-body design judgment call, and that none of these 11
    # responses are confirmed against a live capture yet.

    @router.post("/phr/consent/auto-approve", summary="Auto-approve policy (SS6.13) -- 202 Accepted expected, no documented response")
    def consent_auto_approve(body: AutoApproveBody) -> dict:
        return _passthrough(consent.auto_approve(  # type: ignore[arg-type]
            settings, body.xToken, body.hiuId, body.hiTypes, body.purposeText, body.purposeCode,
            body.purposeRefUri, body.periodFrom, body.periodTo, body.isApplicableForAllHIPs,
        ))

    @router.post("/phr/consent/auto-approve/disable", summary="Disable auto-approve policy (SS6.14)")
    def consent_auto_approve_disable(body: SetAutoApproveStateBody) -> dict:
        return _passthrough(consent.disable_auto_approve(settings, body.xToken, body.consentId))  # type: ignore[arg-type]

    @router.post("/phr/consent/auto-approve/enable", summary="Enable auto-approve policy (SS6.15)")
    def consent_auto_approve_enable(body: SetAutoApproveStateBody) -> dict:
        return _passthrough(consent.enable_auto_approve(settings, body.xToken, body.consentId))  # type: ignore[arg-type]

    @router.post("/phr/consent/requests/get-all", summary="Get All Consent Requests (SS6.16) -- the consent-request inbox")
    def consent_requests_get_all(body: GetAllConsentRequestsBody) -> dict:
        return _passthrough(consent.get_all_consent_requests(settings, body.xToken, body.limit, body.offset, body.status))  # type: ignore[arg-type]

    @router.post("/phr/consent/requests/get-one", summary="Consent Request Details (SS6.17) -- also the pre-fill source for Approve")
    def consent_requests_get_one(body: GetConsentRequestDetailsBody) -> dict:
        return _passthrough(consent.get_consent_request_details(settings, body.xToken, body.consentRequestId))  # type: ignore[arg-type]

    @router.post("/phr/consent/requests/approve", summary="Approve (Postman-only, NOT in the spec PDF -- see consent.py)")
    def consent_requests_approve(body: ApproveConsentRequestBody) -> dict:
        return _passthrough(consent.approve_consent_request(settings, body.xToken, body.consentRequestId, body.consents))  # type: ignore[arg-type]

    @router.post("/phr/consent/requests/deny", summary="Deny (SS6.21)")
    def consent_requests_deny(body: DenyConsentRequestBody) -> dict:
        return _passthrough(consent.deny_consent_request(settings, body.xToken, body.consentRequestId, body.reason))  # type: ignore[arg-type]

    @router.post("/phr/consent/revoke", summary="Revoke (SS6.22) -- acts on already-GRANTED artefacts, not a pending request")
    def consent_revoke(body: RevokeConsentsBody) -> dict:
        return _passthrough(consent.revoke_consents(settings, body.xToken, body.consentIds))  # type: ignore[arg-type]

    @router.post("/phr/consent/artefacts/get-by-request", summary="Consent Artefact Details by Request ID (SS6.18) -- an array")
    def consent_artefacts_get_by_request(body: GetConsentArtefactsByRequestBody) -> dict:
        return _passthrough(consent.get_consent_artefacts_by_request(settings, body.xToken, body.consentRequestId))  # type: ignore[arg-type]

    @router.post("/phr/consent/artefacts/get-one", summary="Consent Artefact Details by Artefact ID (SS6.19)")
    def consent_artefacts_get_one(body: GetConsentArtefactBody) -> dict:
        return _passthrough(consent.get_consent_artefact(settings, body.xToken, body.consentId))  # type: ignore[arg-type]

    @router.post("/phr/consent/artefacts/get-all", summary="All Consent Artefacts (SS6.20) -- \"My Active Consents\"")
    def consent_artefacts_get_all(body: GetAllConsentArtefactsBody) -> dict:
        return _passthrough(consent.get_all_consent_artefacts(settings, body.xToken, body.limit, body.offset, body.status))  # type: ignore[arg-type]

    # -- Provider Directory (spec SS10.3.13-15) -------------------------------
    # Three stateless, read-only GETs under abdm_gateway_base_url -- a
    # different, more specific host than links.py/consent.py's
    # abdm_hiecm_base_url. No xToken on any of these -- see
    # aegle_phr/phr/providers.py's own banner for the header/host story.

    @router.post("/phr/providers/search", summary="All Providers (SS10.3.13) -- free-text name search, stateCode/districtCode always -1")
    def providers_search(body: SearchProvidersBody) -> dict:
        return _passthrough(providers.search_providers(settings, body.name, body.stateCode, body.districtCode))  # type: ignore[arg-type]

    @router.post("/phr/providers/get-one", summary="Provider by ID (SS10.3.14) -- single object, not an array")
    def providers_get_one(body: GetProviderBody) -> dict:
        return _passthrough(providers.get_provider(settings, body.providerId))  # type: ignore[arg-type]

    @router.post("/phr/providers/govt-programs", summary="Government Programs (SS10.3.15) -- no params")
    def providers_govt_programs(body: GetGovtProgramsBody) -> dict:  # noqa: ARG001 -- body has no fields, kept for POST-body symmetry with every other route here
        return _passthrough(providers.get_govt_programs(settings))  # type: ignore[arg-type]

    # -- Data Flow (spec §7). P20: these no longer wrap repo/ -- the whole
    # section 6/7 chain is this app's own now (aegle_phr/phr/hiu_client.py
    # outbound, aegle_phr/callbacks/hiu_services.py inbound). They return
    # their own {ok, status, body, error} envelope, not an AbdmResult, so
    # these routes do NOT go through _passthrough().
    #
    # MANUAL EQUIVALENTS, NOT THE NORMAL PATH: real data reaches a patient
    # because their Health Locker drives consent -> fetch -> data request
    # automatically off an 8.3.11 alert. These exist for testing and for a
    # complete API surface.
    #
    # P19 removed three routes that used to live here -- self-view-consent,
    # ensure-self-view-auto-approve and discover-self-view-consents -- along
    # with the functions behind them. Records now reach a patient only via
    # the Health Locker (see the locker routes further below).

    @router.post("/phr/data-flow/request", summary="Health Information Request (§7.3.1). Checks the consent artefact we hold before spending a round trip.")
    def data_flow_request(body: RequestHealthInformationBody) -> dict:
        return data_flow.request_health_information(
            settings, body.consentId, body.hipId, body.hiuId, body.dateRangeFrom, body.dateRangeTo,
        )

    @router.get("/phr/data-flow/status/{request_id}", summary="Poll this app's own correlation state for a Health Information Request -- see data_flow.py")
    def data_flow_status(request_id: str) -> dict:
        return data_flow.get_health_information_status(request_id)

    @router.post("/phr/data-flow/trigger-consent-fetch", summary="Manual §6 consent fetch, for a GRANTED consent whose notify callback never arrived -- see data_flow.py's own banner")
    def data_flow_trigger_consent_fetch(body: TriggerConsentFetchBody) -> dict:
        return data_flow.trigger_consent_fetch(settings, body.consentId, body.hiuId)

    # -- Health Locker (P19) -- the ONLY route by which a patient's records
    # reach this app. See aegle_phr/phr/locker_service.py's own banner.
    # These return their own {ok, ...} envelopes, not AbdmResult, so they
    # don't go through _passthrough().

    @router.post("/phr/locker/status", summary="P19 -- is this patient's locker set up and usable? Drives the opt-in screen. Read-only, creates nothing.")
    def locker_status(body: LockerStatusBody) -> dict:
        return locker_service.get_locker_status(settings, body.xToken, body.patientAbhaAddress)

    @router.post("/phr/locker/setup", summary="P19 -- 8.3.18 Setup Locker, run only after the patient presses Allow on the opt-in screen. Creates the granted subscription AND its auto-approval policy in one call.")
    def locker_setup(body: LockerSetupBody) -> dict:
        return locker_service.setup_locker_for_patient(settings, body.xToken, body.patientAbhaAddress)

    @router.post("/phr/locker/decline", summary="P19 -- records that the patient said 'Not now' (or opted out), so the automation never silently re-subscribes them.")
    def locker_decline(body: LockerDeclineBody) -> dict:
        state = (
            locker_repository.OPT_IN_OPTED_OUT if body.optedOut
            else locker_repository.OPT_IN_DECLINED
        )
        row = locker_repository.set_opt_in(
            body.patientAbhaAddress, settings.abdm_health_locker_id, state,
        )
        # P20 -- withdrawing permission erases what we hold. Run for BOTH
        # states, not just OPTED_OUT: "Not now" from someone who never
        # allowed is a no-op (nothing was collected), and reasoning about
        # which path can have data behind it is exactly the kind of
        # cleverness that leaves records behind after a withdrawal.
        erasure = retention.erase_for_patient(
            body.patientAbhaAddress, settings.abdm_health_locker_id, f"patient opt-in set to {state}",
        )
        return {"ok": True, "status": 200, "body": row, "erasure": erasure, "error": None}

    @router.post("/phr/locker/initial-sync", summary="P19 -- one-off backfill of care contexts linked BEFORE the subscription existed (alerts only cover what is linked after).")
    def locker_initial_sync(body: LockerInitialSyncBody) -> dict:
        return locker_service.run_initial_sync(settings, body.xToken, body.patientAbhaAddress, force=body.force)

    @router.post("/phr/locker/records", summary="P20 -- everything the locker currently holds for this patient, read from local storage. No ABDM call. Sweeps lapsed consents first, and starts the one-off backfill if it has never run.")
    def locker_records(body: LockerRecordsBody, background: BackgroundTasks) -> dict:
        """
        THE LOGIN READ. A locker is entitled to store records for the life
        of the consent behind them, so this is a database read rather than
        a round trip per hospital -- which is the entire practical benefit
        of being a locker rather than a proxy.

        SWEEPS BEFORE IT SERVES. Reading is the moment we would otherwise
        hand over data, so a consent whose retention deadline has passed is
        erased first. That ordering matters: it makes it structurally
        impossible to serve a record we are no longer entitled to hold,
        even once, even if no sweep has run for months.

        STARTS THE BACKFILL, DOES NOT WAIT FOR IT. 8.3.11 alerts only cover
        care contexts linked AFTER the subscription existed, so a patient's
        existing history needs one backfill pass. It is a real ABDM round
        trip per hospital (5-10s observed), so it runs in the background
        and this returns immediately with whatever is already held plus
        initialSyncState -- the caller polls rather than blocking a login
        on it.
        """
        patient_id = body.patientAbhaAddress
        locker_id = settings.abdm_health_locker_id

        retention.sweep_expired(patient_id=patient_id)

        local = locker_repository.get_patient_locker(patient_id, locker_id)
        sync_state = (local or {}).get("initialSyncState")
        opted_in = (local or {}).get("optInState") == locker_repository.OPT_IN_ALLOWED

        if opted_in and body.xToken and sync_state == locker_repository.SYNC_NOT_STARTED:
            background.add_task(
                locker_service.run_initial_sync, settings, body.xToken, patient_id,
            )
            sync_state = locker_repository.SYNC_RUNNING

        records = locker_hiu_repository.get_records_for_patient(patient_id)
        return {
            "ok": True,
            "status": 200,
            "body": {
                "lockerId": locker_id,
                "optInState": (local or {}).get("optInState"),
                "initialSyncState": sync_state,
                "count": len(records),
                "records": records,
            },
            "error": None,
        }

    @router.post("/phr/locker/alerts", summary="P19 -- this patient's locker alert log: every LINK/DATA event and how far it got (received -> consent -> data).")
    def locker_alerts(body: LockerAlertsBody) -> dict:
        return {"ok": True, "status": 200,
                "body": {"alerts": locker_repository.get_alerts_for_patient(body.patientAbhaAddress, body.limit)},
                "error": None}

    # -- Subscription Flow (spec §8) -- see aegle_phr/phr/subscription.py's
    # own module banner for the full URL/body provenance.
    # get-local-subscriptions is a debugging/UI helper reading straight
    # from subscription_repository, not an ABDM call, so it isn't
    # _passthrough()-wrapped.
    #
    # P19 removed /phr/subscription/ensure-self-subscription (8.3.2 with
    # hiu.id=CLIENT_ID) -- superseded by the locker routes above.

    @router.post("/phr/subscription/get-local", summary="P13 -- every locally-known subscription attempt for one patient (subscription_request table), no live ABDM round trip")
    def subscription_get_local(body: GetLocalSubscriptionsBody) -> dict:
        return {"ok": True, "status": 200, "body": {"subscriptions": get_all_local_subscriptions_for_patient(body.patientAbhaAddress)}, "error": None}

    @router.post("/phr/subscription/requests/get-all", summary="8.3.1 -- Get all subscription requests")
    def subscription_get_all_requests(body: GetAllSubscriptionRequestsBody) -> dict:
        return _passthrough(subscription.get_all_subscription_requests(settings, body.xToken, body.limit, body.offset, body.status))  # type: ignore[arg-type]

    @router.post("/phr/subscription/approve", summary="8.3.4 -- Approve subscription request")
    def subscription_approve(body: ApproveSubscriptionRequestBody) -> dict:
        return _passthrough(subscription.approve_subscription_request(  # type: ignore[arg-type]
            settings, body.xToken, body.subscriptionRequestId, body.isApplicableForAllHIPs,
            body.hiTypes, body.categories, body.periodFrom, body.periodTo,
            body.purposeText, body.purposeCode, body.purposeRefUri, body.hipId, body.hipName,
        ))

    @router.post("/phr/subscription/deny", summary="8.3.7 -- Deny subscription request")
    def subscription_deny(body: DenySubscriptionRequestBody) -> dict:
        return _passthrough(subscription.deny_subscription_request(settings, body.xToken, body.subscriptionRequestId, body.reason))  # type: ignore[arg-type]

    @router.post("/phr/subscription/edit", summary="8.3.9 -- Edit subscription (the one PUT in this section)")
    def subscription_edit(body: EditSubscriptionBody) -> dict:
        return _passthrough(subscription.edit_subscription(  # type: ignore[arg-type]
            settings, body.xToken, body.approvedSubscriptionId, body.hiuId, body.isApplicableForAllHIPs,
            body.hiTypes, body.categories, body.periodFrom, body.periodTo,
            body.purposeText, body.purposeCode, body.purposeRefUri,
        ))

    @router.post("/phr/subscription/details-by-request-id", summary="8.3.13 -- Subscription details by request id")
    def subscription_details_by_request_id(body: GetSubscriptionDetailsByRequestIdBody) -> dict:
        return _passthrough(subscription.get_subscription_details_by_request_id(settings, body.xToken, body.subscriptionRequestId))  # type: ignore[arg-type]

    @router.post("/phr/subscription/details-by-subscription-id", summary="8.3.14 -- Subscription details by subscription id (URL per Postman, see subscription.py's own discrepancy note)")
    def subscription_details_by_subscription_id(body: GetSubscriptionDetailsBySubscriptionIdBody) -> dict:
        return _passthrough(subscription.get_subscription_details_by_subscription_id(settings, body.xToken, body.subscriptionId))  # type: ignore[arg-type]

    @router.post("/phr/subscription/patients/requests", summary="8.3.15 -- Get all subscription+consent requests")
    def subscription_get_all_patient_requests(body: GetAllPatientRequestsBody) -> dict:
        return _passthrough(subscription.get_all_patient_requests(  # type: ignore[arg-type]
            settings, body.xToken, body.consentLimit, body.consentOffset,
            body.subscriptionLimit, body.subscriptionOffset, body.status,
        ))

    @router.post("/phr/subscription/lockers/get-all", summary="8.3.16 -- Get patient's subscribed lockers")
    def subscription_get_lockers(body: GetPatientSubscribedLockersBody) -> dict:
        return _passthrough(subscription.get_patient_subscribed_lockers(settings, body.xToken, body.includeInactive))  # type: ignore[arg-type]

    @router.post("/phr/subscription/lockers/get-one", summary="8.3.17 -- Locker details by locker id")
    def subscription_get_locker_details(body: GetLockerDetailsBody) -> dict:
        return _passthrough(subscription.get_locker_details(settings, body.xToken, body.lockerId))  # type: ignore[arg-type]

    @router.post("/phr/subscription/setup-locker", summary="8.3.18 -- Setup Locker (X-LOCKER-ID) -- see R2 in CC_PROMPT_P13_subscription_flow_full_build.md")
    def subscription_setup_locker(body: SetupLockerBody) -> dict:
        return _passthrough(subscription.setup_locker(settings, body.xToken, body.lockerId))  # type: ignore[arg-type]

    @router.post("/phr/subscription/disable", summary="Disable subscription -- Postman-only, no spec number")
    def subscription_disable(body: SetSubscriptionStateBody) -> dict:
        return _passthrough(subscription.disable_subscription(settings, body.xToken, body.subscriptionId))  # type: ignore[arg-type]

    @router.post("/phr/subscription/enable", summary="Enable subscription -- Postman-only, no spec number")
    def subscription_enable(body: SetSubscriptionStateBody) -> dict:
        return _passthrough(subscription.enable_subscription(settings, body.xToken, body.subscriptionId))  # type: ignore[arg-type]

    # -- User-Initiated Linking (spec §10.3.1-§10.3.12) -- P15 ----------------
    # Asynchronous: all three outbound calls below return a bare 202
    # Accepted, and this backend generates its own REQUEST-ID up front (not
    # inside uil.py -- here, so a UilLinkRequest row can be saved BEFORE the
    # call completes, same ordering data_flow.py's own subscription
    # functions use) and hands it back to the frontend as `requestId`,
    # which is what GET /phr/uil/result below is then polled with. See
    # aegle_phr/phr/uil.py's own module banner for the header/host/body
    # provenance and aegle_phr/callbacks/uil_services.py for what happens
    # when each of the three matching callbacks actually arrives.

    @router.post("/phr/uil/discover", summary="10.3.1 -- Discover care contexts at a HIP -- 202 Accepted, real answer via the on-discover callback")
    def uil_discover(body: UilDiscoverBody) -> dict:
        request_id = generate_request_id()
        save_new_uil_request(request_id, stage="discover", hip_id=body.hipId, abha_address=body.abhaAddress, detail={"hipId": body.hipId, "abhaAddress": body.abhaAddress})
        payload = _passthrough(uil.discover(settings, body.xToken, body.hipId, body.abhaAddress, request_id=request_id))  # type: ignore[arg-type]
        payload["requestId"] = request_id
        return _record_uil_failure(request_id, payload)

    @router.post("/phr/uil/link-init", summary="10.3.5 -- Link init -- SENDS A REAL OTP -- 202 Accepted, real answer via the on-init callback")
    def uil_link_init(body: UilLinkInitBody) -> dict:
        request_id = generate_request_id()
        save_new_uil_request(request_id, stage="link_init", hip_id=body.hipId, abha_address=body.abhaAddress, detail={"transactionId": body.transactionId})
        payload = _passthrough(uil.link_init(settings, body.xToken, body.transactionId, body.abhaAddress, body.patientMatches, request_id=request_id))  # type: ignore[arg-type]
        payload["requestId"] = request_id
        return _record_uil_failure(request_id, payload)

    @router.post("/phr/uil/link-confirm", summary="10.3.9 -- Link confirm (the real OTP) -- 202 Accepted, real answer via the on-confirm callback")
    def uil_link_confirm(body: UilLinkConfirmBody) -> dict:
        request_id = generate_request_id()
        save_new_uil_request(request_id, stage="link_confirm", hip_id=body.hipId, abha_address=body.abhaAddress, detail={"linkRefNumber": body.linkRefNumber})
        payload = _passthrough(uil.link_confirm(settings, body.xToken, body.token, body.linkRefNumber, request_id=request_id))  # type: ignore[arg-type]
        payload["requestId"] = request_id
        return _record_uil_failure(request_id, payload)

    @router.get("/phr/uil/result", summary="Poll one UilLinkRequest row by requestId -- the frontend's own async-wait mechanism for all three calls above")
    def uil_result(requestId: str = Query(min_length=1)) -> dict:
        row = get_uil_request_by_id(requestId)
        return {"ok": True, "status": 200, "body": row, "error": None}

    # -- ABHA Address creation for an EXISTING ABHA Number (P1-H) -------------
    # Aayush's third top-level entry point, distinct from Login and Signup --
    # see aegle_phr/phr/abha_address_creation.py's own banner. Verify
    # ownership (either variant below), then reuse the SAME suggestion/
    # isExists/enrol routes already defined above for the mobile-based
    # enrollment flow -- confirmed identical in shape against Aayush's own
    # Postman collection. Both variants go straight from verify to
    # suggestion -- no verify/user step for either (an earlier version
    # added one for the mobile variant; removed, see that module's banner).

    @router.post("/phr/abha-address/request-otp-aadhaar", summary="ABHA Address creation step 1 (Aadhaar OTP) — SENDS A REAL OTP via UIDAI")
    def abha_address_request_otp_aadhaar(body: RequestAbhaAddressCreationAadhaarOtpBody) -> dict:
        return _passthrough(abha_address_creation.request_otp_via_aadhaar(settings, body.abhaNumber))  # type: ignore[arg-type]

    @router.post("/phr/abha-address/verify-otp-aadhaar", summary="ABHA Address creation step 2 (Aadhaar OTP) — verify, then straight to suggestion/enrol")
    def abha_address_verify_otp_aadhaar(body: VerifyOtpBody) -> dict:
        return _passthrough(abha_address_creation.verify_otp_via_aadhaar(settings, body.txnId, body.otp))  # type: ignore[arg-type]

    @router.post("/phr/abha-address/request-otp-mobile", summary="ABHA Address creation step 1 (mobile OTP) — SENDS A REAL SMS")
    def abha_address_request_otp_mobile(body: RequestAbhaAddressCreationMobileOtpBody) -> dict:
        return _passthrough(abha_address_creation.request_otp_via_mobile(settings, body.abhaNumber))  # type: ignore[arg-type]

    @router.post("/phr/abha-address/verify-otp-mobile", summary="ABHA Address creation step 2 (mobile OTP) — verify, then straight to suggestion/enrol")
    def abha_address_verify_otp_mobile(body: VerifyOtpBody) -> dict:
        return _passthrough(abha_address_creation.verify_otp_via_mobile(settings, body.txnId, body.otp))  # type: ignore[arg-type]

    # -- Email verification link (P1-F, added by request) --------------------
    # POST-registration action, not part of enrollment -- requires an
    # already-issued session token. Fire-and-forget: no verify/OTP step
    # exists for this flow anywhere in this project's reference code.

    @router.post("/phr/profile/request-email-verification-link", summary="Send a real email verification link (requires a session token)")
    def request_email_verification_link(body: RequestEmailVerificationLinkBody) -> dict:
        return _passthrough(email_verification.request_email_verification_link(settings, body.xToken, body.email))  # type: ignore[arg-type]

    # -- Password login for an existing ABHA address (P1-C) -----------------
    # Three flat steps, same pattern as enrollment above. verify's success
    # shape is undocumented -- see aegle_phr/phr/login.py's banner.

    @router.post("/phr/login/search", summary="Password login step 1 — search ABHA address")
    def login_search(body: SearchUserBody) -> dict:
        return _passthrough(login.search_user(settings, body.abhaAddress))

    @router.post("/phr/login/verify", summary="Password login step 2 — verify password (success shape UNDOCUMENTED)")
    def login_verify(body: VerifyPasswordBody) -> dict:
        return _passthrough(login.verify_password(settings, body.abhaAddress, body.password))

    @router.post("/phr/login/verify-user", summary="Login step (shared) — exchange txnId + tToken for the session token")
    def login_verify_user(body: VerifyLoginUserBody) -> dict:
        return _passthrough(login.verify_user(settings, body.abhaAddress, body.txnId, body.tToken))

    # -- Mobile OTP login (P1-D) ---------------------------------------------
    # First real caller of verify-user above: unlike password login, this
    # verify step doesn't already know which ABHA address it's logging into
    # -- it returns every address linked to the mobile, and the UI picks one.

    @router.post("/phr/login/request-otp", summary="Mobile OTP login step 1 — request OTP (SENDS A REAL SMS)")
    def login_request_otp(body: RequestLoginOtpBody) -> dict:
        return _passthrough(login.request_mobile_otp(settings, body.mobile))

    @router.post("/phr/login/verify-otp", summary="Mobile OTP login step 2 — verify OTP (success shape UNDOCUMENTED)")
    def login_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_mobile_otp(settings, body.txnId, body.otp))

    # -- Five more OTP-based login methods (P1-E) ----------------------------
    # All finish with the shared /phr/login/verify-user route above --
    # nothing new needed there, t_token already required by that route.

    @router.post("/phr/login/abha-number-via-aadhaar/request-otp", summary="ABHA Number login (Aadhaar OTP) step 1 — SENDS A REAL OTP")
    def login_abha_number_aadhaar_request_otp(body: RequestAbhaNumberAadhaarOtpBody) -> dict:
        return _passthrough(login.request_abha_number_aadhaar_otp(settings, body.abhaNumber))

    @router.post("/phr/login/abha-number-via-aadhaar/verify-otp", summary="ABHA Number login (Aadhaar OTP) step 2 — verify (UNDOCUMENTED)")
    def login_abha_number_aadhaar_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_abha_number_aadhaar_otp(settings, body.txnId, body.otp))

    @router.post("/phr/login/aadhaar-number/request-otp", summary="Raw Aadhaar Number login step 1 — SENDS A REAL OTP")
    def login_aadhaar_number_request_otp(body: RequestAadhaarOtpBody) -> dict:
        return _passthrough(login.request_aadhaar_otp(settings, body.aadhaarNumber))

    @router.post("/phr/login/aadhaar-number/verify-otp", summary="Raw Aadhaar Number login step 2 — verify")
    def login_aadhaar_number_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_aadhaar_otp(settings, body.txnId, body.otp))

    @router.post("/phr/login/abha-number-via-mobile/request-otp", summary="ABHA Number login (mobile OTP) step 1 — SENDS A REAL SMS")
    def login_abha_number_mobile_request_otp(body: RequestAbhaNumberMobileOtpBody) -> dict:
        return _passthrough(login.request_abha_number_mobile_otp(settings, body.abhaNumber))

    @router.post("/phr/login/abha-number-via-mobile/verify-otp", summary="ABHA Number login (mobile OTP) step 2 — verify (UNDOCUMENTED)")
    def login_abha_number_mobile_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_abha_number_mobile_otp(settings, body.txnId, body.otp))

    @router.post("/phr/login/abha-address-via-mobile/request-otp", summary="ABHA Address login (mobile OTP) step 1 — SENDS A REAL SMS")
    def login_abha_address_mobile_request_otp(body: RequestAbhaAddressMobileOtpBody) -> dict:
        return _passthrough(login.request_abha_address_mobile_otp(settings, body.abhaAddress))

    @router.post("/phr/login/abha-address-via-mobile/verify-otp", summary="ABHA Address login (mobile OTP) step 2 — verify (UNDOCUMENTED)")
    def login_abha_address_mobile_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_abha_address_mobile_otp(settings, body.txnId, body.otp))

    @router.post("/phr/login/abha-address-via-email/request-otp", summary="ABHA Address login (email OTP) step 1 — SENDS A REAL EMAIL")
    def login_abha_address_email_request_otp(body: RequestAbhaAddressEmailOtpBody) -> dict:
        return _passthrough(login.request_abha_address_email_otp(settings, body.email))

    @router.post("/phr/login/abha-address-via-email/verify-otp", summary="ABHA Address login (email OTP) step 2 — verify (UNDOCUMENTED)")
    def login_abha_address_email_verify_otp(body: VerifyLoginOtpBody) -> dict:
        return _passthrough(login.verify_abha_address_email_otp(settings, body.txnId, body.otp))

    return router


def build_router(settings: Settings) -> APIRouter:
    """
    Every PHR route, in one router: the six inbound ABDM callbacks plus
    GET /phr/health.

    Args:
        settings: The application's Settings. Passed explicitly rather
            than read from a module global so a host can mount the PHR
            with configuration it owns.
    """
    router = APIRouter()
    router.include_router(build_app_api_router(settings))
    # Deliberately NOT gated by X-Aegle-Key -- ABDM cannot send it.
    router.include_router(build_callback_router(settings))
    return router
