"""
Request bodies for THIS app's enrollment routes (UI -> backend).

Request shapes only. There are no response models here beyond what ABDM
actually documents -- see the banner in aegle_phr/phr/enrollment.py. Our
routes hand back ABDM's raw body untouched.

The UI holds the txnId and passes it back on every step. No server-side
state machine: this is a harness, and a flat request/response per step is
what makes the Console panel legible.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RequestOtpBody(BaseModel):
    """Plaintext mobile. Encrypted in enrollment.request_otp(), never stored."""

    mobile: str = Field(min_length=1)


class VerifyOtpBody(BaseModel):
    """Plaintext OTP. Encrypted in enrollment.verify_otp(), never stored."""

    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class SuggestionsBody(BaseModel):
    txnId: str = Field(min_length=1)
    firstName: str = ""
    lastName: str = ""
    dayOfBirth: str = ""
    monthOfBirth: str = ""
    yearOfBirth: str = ""
    # Optional deliberately: the spec's parameter table calls email
    # REQUIRED while its own example body omits it. Sent only if supplied.
    email: str | None = None


class EnrolBody(BaseModel):
    txnId: str = Field(min_length=1)
    mobile: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    password: str = Field(min_length=1)

    firstName: str = ""
    middleName: str = ""
    lastName: str = ""
    dayOfBirth: str = ""
    monthOfBirth: str = ""
    yearOfBirth: str = ""
    gender: str = ""
    email: str = ""
    address: str = ""
    stateName: str = ""
    stateCode: str = ""
    districtName: str = ""
    districtCode: str = ""
    pinCode: str = ""

    def phr_details(self) -> dict[str, str]:
        """The plaintext demographic fields ABDM expects unencrypted."""
        return {
            "firstName": self.firstName,
            "middleName": self.middleName,
            "lastName": self.lastName,
            "dayOfBirth": self.dayOfBirth,
            "monthOfBirth": self.monthOfBirth,
            "yearOfBirth": self.yearOfBirth,
            "gender": self.gender,
            "email": self.email,
            "address": self.address,
            "stateName": self.stateName,
            "stateCode": self.stateCode,
            "districtName": self.districtName,
            "districtCode": self.districtCode,
            "pinCode": self.pinCode,
        }


class RequestAadhaarEnrollmentOtpBody(BaseModel):
    """
    Real Aadhaar-based ABHA enrollment (P1-F), step 1. Sends a REAL OTP via
    UIDAI. Not part of the PHR spec -- ported from repo/server/abha.py's
    request_otp(action="enrollment"), see aegle_phr/phr/aadhaar_enrollment.py.
    """

    aadhaarNumber: str = Field(min_length=1)


class EnrolByAadhaarBody(BaseModel):
    """
    Real Aadhaar-based ABHA enrollment (P1-F), step 2 -- OTP and mobile
    submitted together, no separate verify step. `mobile` is sent to ABDM
    UNENCRYPTED (see aadhaar_enrollment.py's own banner) -- still a real
    plaintext secret as far as this app's own storage is concerned, and
    handled the same way every other plaintext secret in this project is.
    """

    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)
    mobile: str = Field(min_length=1)


class CreateAbhaAddressFromEnrollmentBody(BaseModel):
    """
    ABHA Address creation chained directly off a FRESH Aadhaar enrollment
    (P1-J, M1 test suite Flow 11) -- uses the SAME txnId enrol/byAadhaar's
    own request/otp opened. NOT the suggestion/isExists/enrol chain used
    for an already-existing ABHA Number (a different scenario, confirmed
    live to reject this flow's txnId). `abhaAddress` is the bare local
    part the user wants (e.g. "yourname"); ABDM assembles "yourname@sbx"
    itself.
    """

    txnId: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    preferred: int = 1


class GetAddressSuggestionsFromEnrollmentBody(BaseModel):
    """
    ABHA Address suggestions chained off a FRESH Aadhaar enrollment (P1-K)
    -- NOT implemented in the M1 CLI; ported from Aayush's own Postman
    collection instead (see aegle_phr/phr/aadhaar_enrollment.py's own
    banner). Same txnId family as CreateAbhaAddressFromEnrollmentBody
    above. ABDM's own call is a GET with no body, but this backend's own
    routes are consistently POST+body for every step -- the txnId still
    just travels in our own request JSON; aadhaar_enrollment.py is what
    moves it onto ABDM's Transaction_Id header.
    """

    txnId: str = Field(min_length=1)


class GetAbhaCardBody(BaseModel):
    """
    ABHA card fetch for the "ABHA number already exists" branch of Aadhaar
    registration (P1-L) -- see aegle_phr/phr/abha_card.py's own banner.
    `xToken` is enrol/byAadhaar's own session token (tokens.token),
    confirmed live to work here.
    """

    xToken: str = Field(min_length=1)


class RequestAbhaAddressCreationAadhaarOtpBody(BaseModel):
    """
    ABHA Address creation for an EXISTING ABHA Number (P1-H), via Aadhaar
    OTP -- PHR spec SS3.4-SS3.5. A DIFFERENT flow from Signup (which creates
    the ABHA Number itself) -- this one only ever runs once an ABHA Number
    already exists. Sends a REAL OTP via UIDAI.
    """

    abhaNumber: str = Field(min_length=1)


class RequestAbhaAddressCreationMobileOtpBody(BaseModel):
    """ABHA Address creation for an EXISTING ABHA Number (P1-H), via mobile OTP -- PHR spec SS3.6-SS3.7. Sends a REAL SMS."""

    abhaNumber: str = Field(min_length=1)


class RequestMobileLinkOtpBody(BaseModel):
    """
    Mobile linking, chained off a FRESH Aadhaar enrollment (P1-J, corrected
    from an earlier version that wrongly required a session X-token -- see
    aegle_phr/phr/mobile_linking.py's own banner). No X-token: this chains
    directly off the enrollment's own transaction. `txnId` is the ORIGINAL
    enrollment transaction id (confirmed live 2026-08-31 that a blank one,
    what M1's own Flow 10 literally sends, gets rejected -- see
    mobile_linking.py's own banner for the full story). Sends a REAL SMS.
    """

    txnId: str = Field(min_length=1)
    mobile: str = Field(min_length=1)


class VerifyMobileLinkOtpBody(BaseModel):
    """Mobile linking, step 2 -- see RequestMobileLinkOtpBody. No X-token needed."""

    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class RequestEmailVerificationLinkBody(BaseModel):
    """
    Sends a REAL email containing a clickable verification link (P1-F,
    added by request). Requires an already-issued session token (xToken)
    -- this is a post-registration "link email to my account" action, not
    part of enrollment. No verify step exists for this flow anywhere in
    this project's reference code -- see aegle_phr/phr/email_verification.py.
    """

    xToken: str = Field(min_length=1)
    email: str = Field(min_length=1)


class SearchUserBody(BaseModel):
    """Password login step 1. Plaintext -- an ABHA address is not a secret."""

    abhaAddress: str = Field(min_length=1)


class VerifyPasswordBody(BaseModel):
    """Password login step 2. Plaintext password, encrypted in login.verify_password(), never stored."""

    abhaAddress: str = Field(min_length=1)
    password: str = Field(min_length=1)


class VerifyLoginUserBody(BaseModel):
    """
    Shared login step -- ABDM's own description says every login method's
    verify step feeds into this one. `tToken` is REQUIRED: confirmed live
    2026-08-28 that this ABDM endpoint 401s without it, regardless of
    Authorization -- see aegle_phr/phr/login.py's verify_user() docstring
    for the full story. It is the same value the caller's own verify step
    returned under tokens.token; the caller must carry it forward alongside
    txnId, not just txnId alone.
    """

    abhaAddress: str = Field(min_length=1)
    txnId: str = Field(min_length=1)
    tToken: str = Field(min_length=1)


class RequestLoginOtpBody(BaseModel):
    """Mobile OTP login step 1. Plaintext mobile, encrypted in login.request_mobile_otp(), never stored. SENDS A REAL SMS."""

    mobile: str = Field(min_length=1)


class VerifyLoginOtpBody(BaseModel):
    """
    Verify step for EVERY OTP-based login method (P1-E onward reuses this
    one model rather than declaring five near-identical copies) -- every
    one of them posts the same {txnId, otp} shape to /phr/app/login/verify,
    differing only in `scope`, which login.py's own functions supply.
    Plaintext OTP, encrypted before it leaves this backend, never stored.
    """

    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class RequestAbhaNumberAadhaarOtpBody(BaseModel):
    """ABHA Number login via Aadhaar OTP (SS3.13-14), step 1. Sends a REAL OTP to the Aadhaar-registered mobile."""

    abhaNumber: str = Field(min_length=1)


class RequestAadhaarOtpBody(BaseModel):
    """Raw Aadhaar Number login (SS3.15-16), step 1. Sends a REAL OTP via UIDAI."""

    aadhaarNumber: str = Field(min_length=1)


class RequestAbhaNumberMobileOtpBody(BaseModel):
    """ABHA Number login via Mobile OTP (SS3.17-18), step 1. Sends a REAL SMS to whichever mobile is linked to this ABHA number."""

    abhaNumber: str = Field(min_length=1)


class RequestAbhaAddressMobileOtpBody(BaseModel):
    """ABHA Address login via Mobile OTP (SS3.19-20), step 1. Sends a REAL SMS."""

    abhaAddress: str = Field(min_length=1)


class RequestAbhaAddressEmailOtpBody(BaseModel):
    """
    ABHA Address login via Email OTP (SS3.21-22), step 1. Sends a REAL
    email OTP. The field here is deliberately named `email`, not
    `abhaAddress` -- see login.py's request_abha_address_email_otp() for
    the spec self-contradiction this resolves against the example body.
    """

    email: str = Field(min_length=1)


# --- Profile view + updates for an already logged-in user (P1-M) -----------
# See aegle_phr/phr/profile.py's own banner for the full story on
# certificate choice, headers, and the mobile/email-echo hypothesis.


class GetProfileBody(BaseModel):
    """`xToken`: the real logged-in session token -- see profile.py's own banner for why this URL family needs it, unlike enrollment-chained flows."""

    xToken: str = Field(min_length=1)


class UpdateProfileBody(BaseModel):
    """
    `mobile`/`email`: echoed back UNCHANGED from Get Profile's own
    response -- this screen never lets the user type into these fields
    directly. See profile.py's own banner for the hypothesis this rests
    on. Every other field defaults to "" so a caller only has to supply
    what it actually has.
    """

    xToken: str = Field(min_length=1)
    mobile: str = Field(min_length=1)
    email: str = ""
    firstName: str = ""
    middleName: str = ""
    lastName: str = ""
    dayOfBirth: str = ""
    monthOfBirth: str = ""
    yearOfBirth: str = ""
    gender: str = ""
    address: str = ""
    stateName: str = ""
    stateCode: str = ""
    districtName: str = ""
    districtCode: str = ""
    profilePhoto: str = ""

    def fields(self) -> dict[str, str]:
        """The demographic/address subset profile.update_profile()'s own `fields` param expects."""
        return {
            "firstName": self.firstName,
            "middleName": self.middleName,
            "lastName": self.lastName,
            "dayOfBirth": self.dayOfBirth,
            "monthOfBirth": self.monthOfBirth,
            "yearOfBirth": self.yearOfBirth,
            "gender": self.gender,
            "address": self.address,
            "stateName": self.stateName,
            "stateCode": self.stateCode,
            "districtName": self.districtName,
            "districtCode": self.districtCode,
            "profilePhoto": self.profilePhoto,
        }


class RequestUpdateMobileOtpBody(BaseModel):
    """Update Mobile (SS3.26), step 1. Sends a REAL SMS."""

    xToken: str = Field(min_length=1)
    mobile: str = Field(min_length=1)


class VerifyUpdateMobileOtpBody(BaseModel):
    """Update Mobile (SS3.27), step 2."""

    xToken: str = Field(min_length=1)
    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class RequestUpdateEmailOtpBody(BaseModel):
    """
    Update Email (SS3.28), step 1. Sends a REAL email OTP. A SEPARATE flow
    from RequestEmailVerificationLinkBody -- see profile.py's own banner
    for why both exist.
    """

    xToken: str = Field(min_length=1)
    email: str = Field(min_length=1)


class VerifyUpdateEmailOtpBody(BaseModel):
    """Update Email (SS3.29), step 2."""

    xToken: str = Field(min_length=1)
    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class UpdatePasswordBody(BaseModel):
    """Update Password (SS3.30). No old-password field -- see profile.py's update_password() docstring."""

    xToken: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    password: str = Field(min_length=1)


# --- Link/De-link ABHA Number, Switch Profile, QR/PHR card, Refresh Token
# (P1-N). See aegle_phr/phr/profile_link.py's own banner for the full
# story on certificate choice, three different session-token headers, and
# the DELINK hypothesis.


class LinkAbhaNumberRequestOtpBody(BaseModel):
    """Link/De-link ABHA Number, step 1 (SS3.31/3.34) -- same body for both the mobile and Aadhaar sub-methods, only the route differs. Sends a REAL OTP."""

    xToken: str = Field(min_length=1)
    abhaNumber: str = Field(min_length=1)


class LinkAbhaNumberVerifyOtpBody(BaseModel):
    """Link/De-link ABHA Number, step 2 (SS3.32/3.35)."""

    xToken: str = Field(min_length=1)
    txnId: str = Field(min_length=1)
    otp: str = Field(min_length=1)


class ProcessLinkBody(BaseModel):
    """
    Link/De-link ABHA Number, step 3 (SS3.33/3.36) -- `transactionId` is
    the `txnId` step 2's verify call returned. `action` "DELINK" is a
    hypothesis, unverified live -- see profile_link.py's own banner.
    """

    xToken: str = Field(min_length=1)
    transactionId: str = Field(min_length=1)
    action: Literal["LINK", "DELINK"]


class SwitchProfileRequestBody(BaseModel):
    """Switch Profile, step 1 (SS3.37)."""

    xToken: str = Field(min_length=1)


class SwitchProfileVerifyBody(BaseModel):
    """
    Switch Profile, step 2 (SS3.38) -- `tToken` here is step 1's OWN
    `tokens.token` (a transient, 5-minute-lifetime grant), NOT the
    session's regular X-token -- see profile_link.py's own banner.
    """

    tToken: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    txnId: str = Field(min_length=1)


class GetQrCodeBody(BaseModel):
    """Get QR Code (SS3.40)."""

    xToken: str = Field(min_length=1)


class GetPhrCardBody(BaseModel):
    """Get PHR Card (SS3.41) -- NOT the ABHA card (abha_card.py) -- see profile_link.py's own banner."""

    xToken: str = Field(min_length=1)


class RefreshTokenBody(BaseModel):
    """Generate Refresh Token (SS3.43) -- `rToken` is the refresh token session.ts stored at login, sent as the R-token header."""

    rToken: str = Field(min_length=1)


# --- Get All Linked Records -- HIP-Initiated Linking, spec section 9 ------
# See aegle_phr/phr/links.py's own banner for the SS6.12-vs-SS9.3.5
# contradiction this resolves and why the response shape is unconfirmed.


class GetAllLinkedRecordsBody(BaseModel):
    """`xToken` is carried as the X-AUTH-TOKEN header, NOT X-Token -- see links.py's own banner for why this endpoint's header set differs from every other module."""

    xToken: str = Field(min_length=1)
    limit: int = -1


# --- Consent Manager -- all 11 patient-facing consent flows (spec §6) -----
# Same X-AUTH-TOKEN convention as GetAllLinkedRecordsBody above -- see
# aegle_phr/phr/consent.py's own banner for the full story, including the
# approve-endpoint's spec-PDF omission and its own body-shape judgment call.


class AutoApproveBody(BaseModel):
    """Sets a standing auto-approve policy (SS6.13) -- one includedSources entry, matching the spec's own example; excludedSources is always sent empty. See consent.py's own auto_approve() docstring."""

    xToken: str = Field(min_length=1)
    hiuId: str = Field(min_length=1)
    hiTypes: list[str] = Field(min_length=1)
    purposeText: str = Field(min_length=1)
    purposeCode: str = Field(min_length=1)
    purposeRefUri: str = Field(min_length=1)
    periodFrom: str = Field(min_length=1)
    periodTo: str = Field(min_length=1)
    isApplicableForAllHIPs: bool = True


class SetAutoApproveStateBody(BaseModel):
    """Disable (SS6.14) / Enable (SS6.15) auto-approve -- same body shape (none) for both, same schema for both routes."""

    xToken: str = Field(min_length=1)
    consentId: str = Field(min_length=1)


class GetAllConsentRequestsBody(BaseModel):
    """The consent-request inbox (SS6.16)."""

    xToken: str = Field(min_length=1)
    limit: int = 10
    offset: int = 0
    status: str = "ALL"


class GetConsentRequestDetailsBody(BaseModel):
    """SS6.17 -- also what supplies the pre-fill data for Approve."""

    xToken: str = Field(min_length=1)
    consentRequestId: str = Field(min_length=1)


class ApproveConsentRequestBody(BaseModel):
    """
    NOT IN THE SPEC PDF -- Postman-only, see consent.py's own banner.
    `consents` is taken as a raw list of dicts, not a rigid nested model
    -- deliberately flexible, since this module's own job is to pass
    whatever the frontend built (pre-filled from GetConsentRequestDetails,
    per this chunk's own scope decision) straight through unvalidated,
    matching how ABDM's own request body for this endpoint is structured
    (see approve_consent_request()'s docstring for the confirmed shape).
    """

    xToken: str = Field(min_length=1)
    consentRequestId: str = Field(min_length=1)
    consents: list[dict[str, Any]] = Field(min_length=1)


class DenyConsentRequestBody(BaseModel):
    """SS6.21. Spec's own words: "invoked from the PHR or mobile application.\""""

    xToken: str = Field(min_length=1)
    consentRequestId: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RevokeConsentsBody(BaseModel):
    """SS6.22 -- acts on already-GRANTED artefacts, not a pending request. `consentIds` is an array so one call can revoke several artefacts at once."""

    xToken: str = Field(min_length=1)
    consentIds: list[str] = Field(min_length=1)


class GetConsentArtefactsByRequestBody(BaseModel):
    """SS6.18 -- the granted artefact(s) tied to one request; an array, since one approved-against-multiple-HIPs request produces multiple artefacts."""

    xToken: str = Field(min_length=1)
    consentRequestId: str = Field(min_length=1)


class GetConsentArtefactBody(BaseModel):
    """SS6.19 -- single artefact by its own consent ID."""

    xToken: str = Field(min_length=1)
    consentId: str = Field(min_length=1)


class GetAllConsentArtefactsBody(BaseModel):
    """SS6.20 -- "My Active Consents"."""

    xToken: str = Field(min_length=1)
    limit: int = 10
    offset: int = 0
    status: str = "ALL"


# --- Provider Directory -- all-providers / provider-by-id / govt-programs
# (spec SS10.3.13-15). See aegle_phr/phr/providers.py's own banner: no
# xToken on any of these three -- they're global directory lookups, not
# tied to a patient session.


class SearchProvidersBody(BaseModel):
    """SS10.3.13 -- free-text name search only; stateCode/districtCode always -1 (no ABDM code lookup table exists in this project)."""

    name: str = ""
    stateCode: int = -1
    districtCode: int = -1


class GetProviderBody(BaseModel):
    """SS10.3.14 -- single provider detail by its own id."""

    providerId: str = Field(min_length=1)


class GetGovtProgramsBody(BaseModel):
    """SS10.3.15 -- no params at all."""


# --- Data Flow (spec §7) -- thin wrapper over repo/'s own working M3
# Block 2 pipeline. See aegle_phr/phr/data_flow.py's own banner for why
# this is a one-time, narrow exception to never touching repo/ (reads
# AND CALLS its existing code, never modifies it).


class RequestHealthInformationBody(BaseModel):
    """§7.3.1 -- consentId is the consent ARTEFACT's own id (consentDetail.consentId), not the consent REQUEST's id."""

    consentId: str = Field(min_length=1)
    hipId: str = Field(min_length=1)
    hiuId: str = Field(min_length=1)
    dateRangeFrom: str = Field(min_length=1)
    dateRangeTo: str = Field(min_length=1)


class TriggerConsentFetchBody(BaseModel):
    """Manual nudge for repo/'s own fetch_consent() on a GRANTED consent. Kept pending live verification that locker consents fetch on their own -- see data_flow.py's own banner."""

    consentId: str = Field(min_length=1)
    hiuId: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# P19 -- Health Locker. The only route by which a patient's records reach
# this app; see aegle_phr/phr/locker_service.py's own banner. P19 removed
# RequestSelfViewConsentBody, EnsureSelfViewAutoApproveBody,
# DiscoverSelfViewConsentsBody and EnsureSelfSubscriptionBody along with
# the functions and routes behind them.
# ---------------------------------------------------------------------------

class LockerStatusBody(BaseModel):
    """Is this patient's locker set up and usable? Read-only; drives the opt-in screen."""

    xToken: str = Field(min_length=1)
    patientAbhaAddress: str = Field(min_length=1)


class LockerSetupBody(BaseModel):
    """8.3.18 Setup Locker. Only ever called after the patient presses Allow."""

    xToken: str = Field(min_length=1)
    patientAbhaAddress: str = Field(min_length=1)


class LockerDeclineBody(BaseModel):
    """
    Records a 'Not now' (optedOut=False) or a deliberate opt-out after
    previously allowing (optedOut=True). Either way the automation stops
    asking and never silently re-subscribes -- see PatientLocker's own
    opt_in_state docstring.
    """

    patientAbhaAddress: str = Field(min_length=1)
    optedOut: bool = False


class LockerRecordsBody(BaseModel):
    """
    Reads what the locker currently holds for this patient.

    xToken is OPTIONAL and is used for one thing only: if the one-off
    backfill has never run, it is what lets the locker read the patient's
    linked records to start it. Omitting it still returns everything
    already held -- the read itself needs no patient session, because the
    records are ours to serve.
    """

    patientAbhaAddress: str = Field(min_length=1)
    xToken: str = ""


class LockerInitialSyncBody(BaseModel):
    """One-off backfill of care contexts linked before the subscription existed."""

    xToken: str = Field(min_length=1)
    patientAbhaAddress: str = Field(min_length=1)
    force: bool = False


class LockerAlertsBody(BaseModel):
    """This patient's locker alert log and how far each event got."""

    patientAbhaAddress: str = Field(min_length=1)
    limit: int = 50


# ---------------------------------------------------------------------------
# P13 -- Subscription Flow (spec §8). See aegle_phr/phr/subscription.py's
# own module banner for the full URL/body provenance (spec docx +
# "PHR&HIECM" Postman collection). Every field name below matches that
# module's own function signatures exactly.
# ---------------------------------------------------------------------------

class GetAllSubscriptionRequestsBody(BaseModel):
    """8.3.1."""

    xToken: str = Field(min_length=1)
    limit: int = 10
    offset: int = 0
    status: str = "ALL"


class ApproveSubscriptionRequestBody(BaseModel):
    """8.3.4."""

    xToken: str = Field(min_length=1)
    subscriptionRequestId: str = Field(min_length=1)
    isApplicableForAllHIPs: bool = True
    hiTypes: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    periodFrom: str = Field(min_length=1)
    periodTo: str = Field(min_length=1)
    purposeText: str = "Care Management"
    purposeCode: str = "CAREMGT"
    purposeRefUri: str = "www.abdm.gov.in"
    hipId: str | None = None
    hipName: str | None = None


class DenySubscriptionRequestBody(BaseModel):
    """8.3.7."""

    xToken: str = Field(min_length=1)
    subscriptionRequestId: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EditSubscriptionBody(BaseModel):
    """8.3.9 -- the one PUT in this whole section."""

    xToken: str = Field(min_length=1)
    approvedSubscriptionId: str = Field(min_length=1)
    hiuId: str = Field(min_length=1)
    isApplicableForAllHIPs: bool = True
    hiTypes: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    periodFrom: str = Field(min_length=1)
    periodTo: str = Field(min_length=1)
    purposeText: str = "Care Management"
    purposeCode: str = "CAREMGT"
    purposeRefUri: str = "www.abdm.gov.in"


class GetSubscriptionDetailsByRequestIdBody(BaseModel):
    """8.3.13."""

    xToken: str = Field(min_length=1)
    subscriptionRequestId: str = Field(min_length=1)


class GetSubscriptionDetailsBySubscriptionIdBody(BaseModel):
    """8.3.14."""

    xToken: str = Field(min_length=1)
    subscriptionId: str = Field(min_length=1)


class GetAllPatientRequestsBody(BaseModel):
    """8.3.15 -- combined consent+subscription listing."""

    xToken: str = Field(min_length=1)
    consentLimit: int = 10
    consentOffset: int = 0
    subscriptionLimit: int = 10
    subscriptionOffset: int = 0
    status: str = "ALL"


class GetPatientSubscribedLockersBody(BaseModel):
    """8.3.16."""

    xToken: str = Field(min_length=1)
    includeInactive: bool = True


class GetLockerDetailsBody(BaseModel):
    """8.3.17."""

    xToken: str = Field(min_length=1)
    lockerId: str = Field(min_length=1)


class SetupLockerBody(BaseModel):
    """8.3.18 -- see R2 in CC_PROMPT_P13_subscription_flow_full_build.md: lockerId is caller-supplied, not guessed by this backend."""

    xToken: str = Field(min_length=1)
    lockerId: str = Field(min_length=1)


class SetSubscriptionStateBody(BaseModel):
    """Disable/Enable -- Postman-only, no spec number. Shared body shape, `enable` picks the action."""

    xToken: str = Field(min_length=1)
    subscriptionId: str = Field(min_length=1)


class GetLocalSubscriptionsBody(BaseModel):
    """Debugging/UI helper -- every locally-known subscription attempt for one patient (subscription_repository.get_all_for_patient()), independent of a live ABDM round trip."""


# ---------------------------------------------------------------------------
# P15 -- User-Initiated Linking (spec §10.3.1-§10.3.12). See
# aegle_phr/phr/uil.py's own module banner for the full header/body/host
# provenance. Every field name below matches that module's own function
# signatures exactly.
# ---------------------------------------------------------------------------

class UilDiscoverBody(BaseModel):
    """10.3.1. abhaAddress is sent PLAINTEXT (no encryption anywhere in this call family -- see uil.py's own banner)."""

    xToken: str = Field(min_length=1)
    hipId: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)


class UilLinkInitBody(BaseModel):
    """
    10.3.5 -- SENDS A REAL OTP. patientMatches is the SAME patient[] shape
    on-discover's own callback body returned, echoed back by the frontend
    (which received it via polling GET /phr/uil/result) -- not re-derived
    or re-validated here, matching the spec's own "confirming which of the
    discovered records to link" framing.

    hipId is NOT part of ABDM's own link-init request body (spec's own
    table: transactionId/abhaAddress/patient[] only) -- carried here purely
    so this route can populate the new UilLinkRequest row's own hip_id
    column, same value the frontend already holds from the discover step.
    """

    xToken: str = Field(min_length=1)
    hipId: str = Field(min_length=1)
    transactionId: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    patientMatches: list[dict[str, Any]] = Field(min_length=1)


class UilLinkConfirmBody(BaseModel):
    """
    10.3.9 -- token is the OTP the patient just typed, as a NUMBER per the
    spec's own example (not a string).

    hipId/abhaAddress are NOT part of ABDM's own link-confirm request body
    (spec's own table: token/linkRefNumber only) -- carried here purely so
    this route can populate the new UilLinkRequest row's own columns, same
    values the frontend already holds from earlier in this same flow.
    """

    xToken: str = Field(min_length=1)
    hipId: str = Field(min_length=1)
    abhaAddress: str = Field(min_length=1)
    token: int
    linkRefNumber: str = Field(min_length=1)

    # REMOVED 2026-09-23: a stray REQUIRED `patientAbhaAddress` sat here,
    # appended after the docstring and read by nothing -- the route uses
    # body.abhaAddress. Being required, it rejected 422 every link-confirm
    # that sent the five documented fields, including the frontend's own
    # (testui's UilLinkConfirmBody has never carried it). It made 10.3.9
    # uncallable from the UI. Found live on the first real confirm.
