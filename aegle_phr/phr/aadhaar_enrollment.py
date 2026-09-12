"""
PHR-side wrapper around abdm_core.aadhaar_enrollment (P1-F) -- real
Aadhaar-based ABHA Number creation.

WHAT LIVES HERE VS. abdm_core.aadhaar_enrollment: the actual ABDM request/
response shape is ported into the shared package (genuinely core ABDM
logic, not PHR-specific -- see that module's own banner). This module is
everything that DOES depend on being the PHR app specifically: which
certificate to encrypt against (see _encrypt() below), and archiving to
abdm_call_log with proper redaction.

CERTIFICATE, THE PART MOST LIKELY TO BE GOTTEN WRONG SILENTLY: this flow
encrypts against settings.abdm_profile_certificate_url (the 4096-bit
PROFILE certificate), NOT settings.phr_certificate_url (2048-bit) every
other call in this project uses. repo/tools/m1_test_suite/common.py's
encrypt() calls server/crypto.py's get_public_certificate() with no URL
override, which defaults to exactly this endpoint. Using the wrong
certificate produces ciphertext ABDM silently cannot decrypt -- not an
obvious error, just a mysterious one. get_public_certificate() is already
cached per-URL for precisely this reason (P0-A's design); this module just
has to call it with the right URL, which is the one thing worth asserting
offline before ever going live (see this chunk's verification script).

TWO CALLS, NOT FIVE: request OTP, then enrol_by_aadhaar submits the OTP AND
mobile together -- no separate "verify" step, exactly as repo/server/
abha.py implements it.

REGISTRATION ENDS HERE (corrected, P1-G): this module used to also map
ABDM's ABHAProfile response onto aegle_phr/phr/enrollment.py's enrol()
phrDetails shape (phr_details_from_abha_profile()), feeding a "set a
password" follow-up screen. Removed -- confirmed against Aayush's own
Postman collection that enrol() is for a DIFFERENT scenario entirely
(creating an ABHA Address for an ALREADY-EXISTING ABHA Number, via a
fresh ownership-verification OTP transaction -- not a continuation of
Aadhaar-based enrollment), and separately, that password is a LOGIN
mechanism with no place in the registration sequence regardless of which
endpoint sets it. See testui's AadhaarRegisterScreen.tsx for the UI-side
correction.

MOBILE IS PLAINTEXT in enrol_by_aadhaar's payload -- passed straight
through, matching abdm_core.aadhaar_enrollment's own contract. Still named
in plaintext_secrets below even though redaction.py's _CIPHERTEXT_SAFE_PATHS
treats the "mobile" KEY as ciphertext-safe by default (true for every OTHER
flow in this project, which DOES encrypt under that key) -- passing it as a
plaintext_secret is what makes the VALUE-based scrub (which runs regardless
of that key-based exemption) actually catch it here. See redaction.py's own
module docstring for why both layers exist independently.

REDACTION FOR THE RESPONSE, NOT JUST THE REQUEST: the confirmed real
enrol_by_aadhaar response (Aayush's own Postman example, 2026-08-30) nests
a raw Aadhaar-linked mobile and the full session token inside ABHAProfile/
tokens. "token" is already a _SECRET_KEY_FRAGMENTS entry (added 2026-08-27
for exactly this JWT-embeds-PII reason) and "mobile" is a _CIPHERTEXT_SAFE_
PATHS entry as explained above, but VALUE-based scrubbing (plaintext_secrets)
does not care which key a value sits under -- passing the real mobile number
through plaintext_secrets on BOTH request and response archiving covers it
either way, mirroring enrollment.py's existing single-plaintext_secrets-tuple
pattern (not login.py's more elaborate extra_response_secrets callback --
that mechanism exists for values not knowable until the response arrives;
here mobile/OTP/Aadhaar number are all already known before the call is
made, so the simpler tuple is sufficient).

NOT REDACTED, FLAGGED RATHER THAN SILENTLY FIXED (out of this chunk's
stated scope -- Aayush asked specifically for Aadhaar-number/mobile
treatment, "same as mobile numbers and passwords"): the confirmed response
shape also carries a full demographic profile under ABHAProfile --
firstName/middleName/lastName, dob, gender, a home address, and a base64
FACE PHOTO -- under keys no existing redaction rule recognises
(firstName/middleName/lastName are not "fullname"; "photo" is not covered
at all). This means a live run of THIS flow will store all of that in
abdm_call_log in plaintext, including the photo. Real PII, but adding new
redaction rules for it is a scope decision belonging to whoever reviews
this chunk, not something folded in unasked -- see the change report.
"""

import time
from dataclasses import dataclass
from typing import Any

from abdm_core.aadhaar_enrollment import (
    classify_enrol_by_aadhaar_failure,
    create_abha_address as _abdm_create_abha_address,
    enrol_by_aadhaar as _abdm_enrol_by_aadhaar,
    get_abha_address_suggestions as _abdm_get_address_suggestions,
    request_aadhaar_enrollment_otp as _abdm_request_otp,
)
from abdm_core.observability.flow_logger import log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate

from aegle_phr.phr.call_log import archive
from aegle_phr.settings import Settings


@dataclass(frozen=True)
class AbdmResult:
    """
    Same shape as enrollment.AbdmResult/login.AbdmResult, plus one field:
    known_failure -- set only when the response matched one of
    classify_enrol_by_aadhaar_failure()'s two confirmed wrong-OTP
    signatures. None means either success, or a failure that was NOT
    recognised (the raw body is always still there either way -- this
    field is a convenience annotation, never a gate).
    """

    status_code: int | None
    body: Any
    error: str | None = None
    known_failure: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PROFILE certificate -- NOT the PHR certificate. See module banner."""
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


def _parse(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


# ---------------------------------------------------------------------------
# 1. Request OTP  --  POST /enrollment/request/otp
# ---------------------------------------------------------------------------

def request_otp(settings: Settings, aadhaar_number: str) -> AbdmResult:
    """
    Sends a REAL OTP via UIDAI. Uses the DEFAULT retry classifier
    (connection error/timeout/5xx/429/408) -- faithful to repo/server/
    abha.py's own request_otp(), which has no no-retry override for this
    call, unlike this project's OWN convention for every other OTP-request
    function elsewhere in aegle_phr. See abdm_core.aadhaar_enrollment's
    own docstring for why that convention was deliberately NOT grafted on
    here.
    """
    log_phase("Requesting Aadhaar-based ABHA enrollment OTP (real OTP via UIDAI)")
    login_id = _encrypt(settings, aadhaar_number)
    route = "/phr/aadhaar-enrollment/request-otp"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/request/otp"
    started = time.monotonic()

    try:
        response, payload = _abdm_request_otp(settings.abdm_abha_base_url, login_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Aadhaar enrollment OTP request failed: {exc}")
        archive(route, url, {"loginId": login_id}, None, None, duration_ms, str(exc), (aadhaar_number,))
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, (aadhaar_number,))
    return AbdmResult(status_code=response.status_code, body=body)


# ---------------------------------------------------------------------------
# 2. Enrol by Aadhaar  --  POST /enrollment/enrol/byAadhaar
# ---------------------------------------------------------------------------

def enrol_by_aadhaar(settings: Settings, txn_id: str, otp: str, mobile: str) -> AbdmResult:
    """
    Completes enrollment: OTP + mobile in ONE call, no separate verify step.
    mobile is PLAINTEXT -- see module banner. Uses abdm_core.aadhaar_
    enrollment's default retry classifier (a wrong OTP is a normal 400/422,
    never retried regardless of classifier -- see that module's docstring).

    CONFIRMED EXPECTED SHAPE (Aayush's own Postman example, 2026-08-30,
    still to be verified against a real live run -- see this chunk's
    README capture): {message, txnId, tokens: {token, expiresIn: 1800,
    refreshToken, refreshExpiresIn}, ABHAProfile: {...demographics...},
    isNew}. tokens here is a FULL session grant (expiresIn 1800 + a real
    refreshToken), NOT the short-lived transfer-token shape seen elsewhere
    in this project (expiresIn 300, no refreshToken) -- if this holds live,
    the account may already be fully usable from this one call. Returned
    raw regardless; nothing here assumes the example is exactly right.
    """
    log_phase("Completing Aadhaar-based ABHA enrollment")
    otp_ciphertext = _encrypt(settings, otp)
    route = "/phr/aadhaar-enrollment/enrol"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/enrol/byAadhaar"
    started = time.monotonic()

    try:
        response, payload = _abdm_enrol_by_aadhaar(
            settings.abdm_abha_base_url, txn_id, otp_ciphertext, mobile
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Aadhaar enrollment by Aadhaar failed: {exc}")
        archive(route, url, {"txnId": txn_id}, None, None, duration_ms, str(exc), (otp, mobile))
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    succeeded = 200 <= response.status_code < 300
    known_failure = None if succeeded else classify_enrol_by_aadhaar_failure(body)
    archive(route, url, payload, response.status_code, body, duration_ms, None, (otp, mobile))
    return AbdmResult(status_code=response.status_code, body=body, known_failure=known_failure)


# ---------------------------------------------------------------------------
# 3. Create ABHA Address, chained off the SAME enrollment  --
#    POST /enrollment/enrol/abha-address  (M1 test suite Flow 11)
# ---------------------------------------------------------------------------

def create_abha_address(settings: Settings, txn_id: str, abha_address: str, preferred: int = 1) -> AbdmResult:
    """
    Uses the SAME txnId enrol_by_aadhaar's own request/otp opened -- NOT
    the suggestion/isExists/enrol chain aegle_phr/phr/enrollment.py's own
    functions implement (that trio is for a genuinely different scenario:
    an ALREADY-EXISTING ABHA Number, verified via its own fresh
    ownership-verification transaction -- confirmed live to reject THIS
    flow's txnId with "Transaction is not found for UUID" when tried).
    No encryption at all in this payload -- abha_address/preferred are
    plain, not PII.
    """
    log_phase(f"Creating ABHA address (chained off enrollment): {abha_address}")
    route = "/phr/aadhaar-enrollment/create-address"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/enrol/abha-address"
    started = time.monotonic()

    try:
        response, payload = _abdm_create_abha_address(settings.abdm_abha_base_url, txn_id, abha_address, preferred)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"ABHA Address creation failed: {exc}")
        archive(route, url, {"txnId": txn_id, "abhaAddress": abha_address}, None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, ())
    return AbdmResult(status_code=response.status_code, body=body)


# ---------------------------------------------------------------------------
# 4. ABHA Address suggestions, chained off the SAME enrollment  --
#    GET /enrollment/enrol/suggestion  (NOT in the M1 CLI -- see
#    abdm_core.aadhaar_enrollment's own banner; ported from Aayush's own
#    Postman collection instead)
# ---------------------------------------------------------------------------

def get_address_suggestions(settings: Settings, txn_id: str) -> AbdmResult:
    """
    Uses the SAME txnId enrol_by_aadhaar's own request/otp opened -- same
    family as create_abha_address() above, just a GET with no JSON body
    (txnId travels as a Transaction_Id header instead). Nothing to encrypt:
    no PII in this request at all.
    """
    log_phase("Fetching ABHA address suggestions (chained off enrollment)")
    route = "/phr/aadhaar-enrollment/suggestions"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/enrol/suggestion"
    started = time.monotonic()

    try:
        response, payload = _abdm_get_address_suggestions(settings.abdm_abha_base_url, txn_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"ABHA Address suggestion fetch failed: {exc}")
        archive(route, url, {"txnId": txn_id}, None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, ())
    return AbdmResult(status_code=response.status_code, body=body)
