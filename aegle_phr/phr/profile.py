"""
Profile view + updates for an already logged-in user (P1-M) -- Get Profile,
Update Profile, and the mobile/email/password update pairs. Spec sections
SS3.26-SS3.30 and SS3.39/SS3.42 (`ABHA_PHR_V3_Documents`), cross-checked
against real saved examples in Aayush's own "PHR" Postman collection where
the two disagreed -- each function below says which source it trusts and
why, per this project's standing rule that a captured request/response
beats a spec example every time they conflict.

URL FAMILY, AND THEREFORE CERTIFICATE: every call in this module hits
`/phr/app/login/...` -- the EXACT SAME family mobile OTP login and all
five P1-E login methods already use (aegle_phr/phr/login.py). Those all
correctly encrypt against settings.phr_certificate_url (2048-bit), NOT
settings.abdm_profile_certificate_url (4096-bit, used by aadhaar_enrollment.py/
mobile_linking.py/email_verification.py/abha_card.py -- all of which hit a
genuinely different URL family, `/enrollment/...` or `/profile/account/...`).
Judge by URL family, not by which module was touched most recently -- see
this chunk's own task prompt for the full reasoning. This module's
_encrypt() therefore mirrors login.py's own, not aadhaar_enrollment.py's.

WHY NOT aegle_phr/phr/mobile_linking.py OR email_verification.py: those
solve a DIFFERENT problem -- linking mobile/email during/after a FRESH
Aadhaar enrollment, chained off a transaction-scoped token with no real
login at all (mobile_linking.py's own banner documents a real "Invalid
X-token" failure the first time it tried THIS module's URL family).
This module's context is a genuinely logged-in user with a real session
X-token updating their already-established profile -- independently
confirmed by real saved Postman examples, not just the spec. Both stay
untouched; this is a new, parallel module, not a replacement.

HEADERS -- SPEC AND LIVE POSTMAN DISAGREE, SENDING THE SUPERSET (flagged,
not silently resolved): the spec's own header table for Get Profile names
a header literally called "X-AUTH-TOKEN" (not "Authorization") alongside
"X-token"; the other four calls' spec header tables name "Authorization"
alongside nothing else. The live Postman collection's saved requests for
all five show only "X-token: Bearer {{X-token}}" plus REQUEST-ID/TIMESTAMP
explicitly -- no Authorization row (Postman's own separate apikey-type
auth block may or may not stand in for it -- this project already knows
that collection mixes apikey and gateway-token conventions inconsistently,
and the standing decision, per Aayush directly, is the gateway token via
Authorization everywhere, never apikey). _headers() below sends BOTH
Authorization (gateway token) and X-Token (session token) on every call --
cheapest safe default; Get Profile costs nothing to retry live if one
turns out unnecessary. UNCONFIRMED whether the literal "X-AUTH-TOKEN"
naming is ever actually required -- only chase that if Authorization+
X-Token demonstrably fails on Get Profile specifically.

UPDATE PROFILE'S mobile/email FIELDS -- A HYPOTHESIS, FLAGGED, NOT PROVEN:
the spec's own property table for updateProfile lists Email and Mobile as
request fields, but its own illustrative JSON example omits both entirely.
The live Postman collection's actual saved request body DOES include both
"email" and "mobile" alongside every demographic field -- trusted over the
incomplete spec example. Since dedicated OTP-verified endpoints exist
specifically for CHANGING mobile/email (request_update_mobile_otp()/
verify_update_mobile_otp() and their email equivalents, below), the
working hypothesis is that updateProfile needs those two fields present
but UNCHANGED (echoing whatever Get Profile already returned), not a
second, unverified way to change them -- update_profile() below takes
`mobile`/`email` as required params and sends them PLAINTEXT (matching
Get Profile's own response shape for those fields; nothing here encrypts
them, unlike aadhaar_enrollment.py's enrol(), which genuinely establishes
a NEW mobile with no separate OTP step of its own). NOT INDEPENDENTLY
CONFIRMED LIVE which of {silently accepts a changed value, rejects it,
ignores it} actually happens if a caller sends a DIFFERENT value here --
only that echoing the unchanged value is expected to be safe. Whoever
tests this live: report which one ABDM actually does, don't leave this as
a silent assumption.

PHOTO -- CONFIRMED ABSENT FROM GET PROFILE, DO NOT FABRICATE: neither the
spec's own example nor the real saved Postman example for Get Profile
carries a photo field of any kind. If a reference screenshot shows one, it
did not come from this call. enrol/byAadhaar's own ABHAProfile response
DOES carry a `photo` field (aegle_phr/phr/aadhaar_enrollment.py), but that
data is transaction-scoped to registration and nothing currently persists
it past the registration screens -- so a user who logged in via any of
this project's OTHER login screens (the only way to reach a profile page
today) has no photo available to this module at all. get_profile()
returns whatever ABDM actually sends, unfiltered; if a photo-shaped field
DOES appear live despite both references lacking one, that is new
information for the caller to act on, not something this module assumes
away.

eKYC-LOCK RULE (spec quoted directly): "In the case of an e-KYC user, KYC
details such as name, DOB, and gender will not be updated. However, for a
non-e-KYC user, all details will be updated." This is a UI/editability
concern, not something this backend module enforces -- ABDM itself is the
real authority (a request that changes a locked field when kycStatus is
VERIFIED presumably still gets rejected/ignored server-side regardless of
what this module sends), and the interactive form lives in testui, not
here. See testui/src/profileEdit.ts for the actual lock-rule
implementation and its offline verification.

RETRY: get_profile() (read-only GET) and update_profile() (idempotent --
resubmitting the same fields changes nothing) use the DEFAULT retry
classifier. Every OTP REQUEST call (mobile/email) is NEVER retried, same
reasoning as every other real-SMS/real-email send in this project. Every
VERIFY call (mobile/email OTP, and password) uses the DEFAULT classifier,
matching login.py's verify_password()/verify_mobile_otp() precedent
exactly -- see that module's own banner for why a "second attempt on a
transient failure after ABDM already processed the first" risk is
accepted here the same way it was there, rather than inventing a
stricter rule this project's own precedent doesn't apply elsewhere.

REDACTION: mobile/otp/email/password are already covered by
redaction.py's existing key-based rules ("mobile", "email", "otpvalue",
"password" are all in _SECRET_KEY_FRAGMENTS already) -- nothing new
needed there. update_profile()'s mobile/email are sent PLAINTEXT under
those same keys, which _CIPHERTEXT_SAFE_PATHS treats as ciphertext-safe
by default (correct for every OTHER call in this project, which encrypts
under those keys) -- passing them through plaintext_secrets is what makes
the VALUE-based scrub actually catch them here too, the exact same
mechanism aadhaar_enrollment.py's enrol_by_aadhaar() already relies on for
its own plaintext mobile field. get_profile()'s own response carries
plaintext mobile/email freshly revealed by ABDM (not known to the caller
beforehand) -- covered via extra_response_secrets, the same mechanism
login.py's search_user()/verify_password() already use for their own
undocumented plaintext leaks.
"""

import time
from typing import Any, Callable

import requests
from pydantic import BaseModel

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

MOBILE_PROFILE_SCOPE = ["abha-address-profile", "mobile-verify"]
EMAIL_PROFILE_SCOPE = ["abha-address-profile", "email-verify"]
PASSWORD_PROFILE_SCOPE = ["abha-address-profile", "password-verify"]

_TIMEOUT_SECONDS = 30


class GetProfileResponse(BaseModel):
    """
    Documented AND live-confirmed shape (spec SS3.39 + a real saved Postman
    example, real account hemant.bodhai_test@sbx) -- recorded as a contract,
    not used to gate get_profile()'s actual return value (that stays raw,
    same convention as every other module in this project).
    """

    abhaAddress: str
    fullName: str | None = None
    firstName: str | None = None
    middleName: str | None = None
    lastName: str | None = None
    dayOfBirth: str | None = None
    monthOfBirth: str | None = None
    yearOfBirth: str | None = None
    dateOfBirth: str | None = None
    gender: str | None = None
    email: str | None = None
    mobile: str | None = None
    abhaNumber: str | None = None
    address: str | None = None
    stateName: str | None = None
    districtName: str | None = None
    pinCode: str | None = None
    stateCode: str | None = None
    districtCode: str | None = None
    authMethods: list[str] = []
    status: str | None = None
    emailVerified: bool | None = None
    mobileVerified: bool | None = None
    kycStatus: str | None = None
    abhaLinkedCount: int | None = None


def _headers(x_token: str) -> dict[str, str]:
    """Both Authorization and X-Token, always -- see module banner's HEADERS section."""
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-Token": f"Bearer {x_token}",
    }


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _never_transient(response: Any, exception: Any) -> bool:
    """Classifier for OTP REQUEST calls -- see enrollment.request_otp()'s own docstring for the full reasoning; identical here."""
    return False


def _execute(
    route: str,
    method: str,
    url: str,
    x_token: str,
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
    extra_response_secrets: Callable[[Any], tuple[str, ...]] | None = None,
    retry: bool = True,
) -> AbdmResult:
    """Performs one ABDM call, archives it, returns the raw result. Never calls raise_for_status() -- see enrollment.py's own _execute() for why."""
    headers = _headers(x_token)
    started = time.monotonic()

    def attempt() -> requests.Response:
        if method == "GET":
            return requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    try:
        if retry:
            response = call_with_retry(attempt, description=description)
        else:
            response = call_with_retry(
                attempt, description=description, is_transient=_never_transient, max_attempts=1
            )
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, payload, None, None, duration_ms, str(exc), plaintext_secrets)
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    all_secrets = plaintext_secrets
    if extra_response_secrets is not None:
        all_secrets = tuple(plaintext_secrets) + tuple(extra_response_secrets(body))

    log_api_call(description, url, response.status_code)
    archive(route, url, payload, response.status_code, body, duration_ms, None, all_secrets)

    return AbdmResult(status_code=response.status_code, body=body)


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PHR certificate -- see module banner's URL FAMILY section for why THIS certificate, not the profile one."""
    public_key = get_public_certificate(settings.phr_certificate_url)
    return encrypt_value(value, public_key)


def _plaintext_string_fields(body: Any, *field_names: str) -> tuple[str, ...]:
    """Mirrors login.py's own helper of the same name -- duplicated, not imported, matching this project's per-module-helper convention."""
    if not isinstance(body, dict):
        return ()
    found = []
    for name in field_names:
        value = body.get(name)
        if isinstance(value, str) and value != "":
            found.append(value)
    return tuple(found)


# ---------------------------------------------------------------------------
# 1. Get Profile  --  GET /phr/app/login/profile  --  spec SS3.39
# ---------------------------------------------------------------------------

def get_profile(settings: Settings, x_token: str) -> AbdmResult:
    """
    Confirmed identically by the spec AND a real saved Postman example --
    see GetProfileResponse above for the full field list. No photo field
    anywhere -- see module banner's PHOTO section.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile"

    log_phase("Fetching profile")
    return _execute(
        route="/phr/profile/get",
        method="GET",
        url=url,
        x_token=x_token,
        payload=None,
        description="PHR get profile",
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )


# ---------------------------------------------------------------------------
# 2. Update Profile  --  POST /phr/app/login/profile/updateProfile  --  spec SS3.42
# ---------------------------------------------------------------------------

def update_profile(
    settings: Settings,
    x_token: str,
    mobile: str,
    email: str,
    fields: dict[str, str],
) -> AbdmResult:
    """
    `mobile`/`email`: echoed back UNCHANGED from Get Profile's own response,
    sent PLAINTEXT -- see module banner's UPDATE PROFILE section for the
    full hypothesis this rests on, flagged as unconfirmed until tested live.

    `fields`: the editable demographic/address fields (firstName,
    middleName, lastName, dayOfBirth, monthOfBirth, yearOfBirth, gender,
    address, stateName, stateCode, districtName, districtCode,
    profilePhoto) -- sent AS GIVEN, whatever the caller decided was safe to
    include given the eKYC-lock rule (this module does not enforce that
    rule itself -- see module banner). Missing keys default to "".

    Success response: confirmed identical shape to Get Profile's, per a
    real saved Postman example -- returned raw regardless, same convention
    as every other call in this project.

    RETRY: default classifier -- resubmitting identical field values is
    idempotent, unlike an OTP/password single-use secret.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/updateProfile"

    payload = {
        "mobile": mobile,
        "email": email,
        "firstName": fields.get("firstName", ""),
        "middleName": fields.get("middleName", ""),
        "lastName": fields.get("lastName", ""),
        "dayOfBirth": fields.get("dayOfBirth", ""),
        "monthOfBirth": fields.get("monthOfBirth", ""),
        "yearOfBirth": fields.get("yearOfBirth", ""),
        "gender": fields.get("gender", ""),
        "address": fields.get("address", ""),
        "stateName": fields.get("stateName", ""),
        "stateCode": fields.get("stateCode", ""),
        "districtName": fields.get("districtName", ""),
        "districtCode": fields.get("districtCode", ""),
        "profilePhoto": fields.get("profilePhoto", ""),
    }

    log_phase("Updating profile")
    return _execute(
        route="/phr/profile/update",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update profile",
        plaintext_secrets=(mobile, email),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )


# ---------------------------------------------------------------------------
# 3. Update Mobile  --  request/verify pair  --  spec SS3.26/SS3.27
# ---------------------------------------------------------------------------

def request_update_mobile_otp(settings: Settings, x_token: str, mobile: str) -> AbdmResult:
    """Sends a REAL SMS. Never retried -- see module banner's RETRY section."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/request/otp"

    payload = {
        "scope": MOBILE_PROFILE_SCOPE,
        "loginHint": "mobile-number",
        "loginId": _encrypt(settings, mobile),
        "otpSystem": "abdm",
    }

    log_phase("Requesting profile mobile-update OTP (real SMS)")
    return _execute(
        route="/phr/profile/update-mobile/request-otp",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update-mobile OTP request",
        plaintext_secrets=(mobile,),
        retry=False,
    )


def verify_update_mobile_otp(settings: Settings, x_token: str, txn_id: str, otp: str) -> AbdmResult:
    """
    Confirmed success shape, real saved Postman example: {txnId, message:
    "Mobile Number linked successfully", authResult: "success", users:
    [{abhaAddress}]}.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/verify"

    payload = {
        "scope": MOBILE_PROFILE_SCOPE,
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "txnId": txn_id,
                "otpValue": _encrypt(settings, otp),
            },
        },
    }

    log_phase("Verifying profile mobile-update OTP")
    return _execute(
        route="/phr/profile/update-mobile/verify-otp",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update-mobile OTP verify",
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )


# ---------------------------------------------------------------------------
# 4. Update Email  --  request/verify pair  --  spec SS3.28/SS3.29
# ---------------------------------------------------------------------------
# A SEPARATE module from aegle_phr/phr/email_verification.py -- that one is
# a fire-and-forget clickable-link email (/profile/account/request/
# emailVerificationLink, ported from the M1 sibling repo, used during
# registration). This is the spec's own OTP-verified profile-update pair, a
# different ABDM endpoint entirely. Both kept; neither merged nor replaced.

def request_update_email_otp(settings: Settings, x_token: str, email: str) -> AbdmResult:
    """Sends a REAL email OTP. Never retried -- see module banner's RETRY section."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/request/otp"

    payload = {
        "scope": EMAIL_PROFILE_SCOPE,
        "loginHint": "email",
        "loginId": _encrypt(settings, email),
        "otpSystem": "abdm",
    }

    log_phase("Requesting profile email-update OTP (real email)")
    return _execute(
        route="/phr/profile/update-email/request-otp",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update-email OTP request",
        plaintext_secrets=(email,),
        retry=False,
    )


def verify_update_email_otp(settings: Settings, x_token: str, txn_id: str, otp: str) -> AbdmResult:
    """
    Confirmed success shape, real saved Postman example: {txnId, message:
    "Email linked successfully", authResult: "success", users:
    [{abhaAddress}]}.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/verify"

    payload = {
        "scope": EMAIL_PROFILE_SCOPE,
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "txnId": txn_id,
                "otpValue": _encrypt(settings, otp),
            },
        },
    }

    log_phase("Verifying profile email-update OTP")
    return _execute(
        route="/phr/profile/update-email/verify-otp",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update-email OTP verify",
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )


# ---------------------------------------------------------------------------
# 5. Update Password  --  POST /phr/app/login/profile/verify  --  spec SS3.30
# ---------------------------------------------------------------------------

def update_password(settings: Settings, x_token: str, abha_address: str, new_password: str) -> AbdmResult:
    """
    No old-password field exists anywhere -- confirmed by searching the
    whole Postman collection. ABDM apparently checks server-side that the
    new password differs from the old one (per the spec's own prose); the
    request only ever carries the new value.

    Confirmed success shape, real saved Postman example, matches spec
    exactly: {message: "Password updated successfully", authResult:
    "success", users: [{abhaAddress}]}.

    RETRY: default classifier -- matches login.py's verify_password()
    precedent exactly (a resubmitted password attempt after a transient
    failure is a structurally identical risk to one already accepted
    there; see that module's own banner for the full reasoning rather than
    inventing a stricter rule here that precedent doesn't apply elsewhere).
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/verify"

    payload = {
        "scope": PASSWORD_PROFILE_SCOPE,
        "authData": {
            "authMethods": ["password"],
            "password": {
                "abhaAddress": abha_address,
                "password": _encrypt(settings, new_password),
            },
        },
    }

    log_phase(f"Updating password for {abha_address}")
    return _execute(
        route="/phr/profile/update-password",
        method="POST",
        url=url,
        x_token=x_token,
        payload=payload,
        description="PHR update password",
        plaintext_secrets=(new_password,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )
