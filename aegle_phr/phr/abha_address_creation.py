"""
ABHA Address creation for an EXISTING ABHA Number (P1-H) -- Aayush's third
top-level entry point, distinct from both Login and Signup:

    1. Login    -- an existing ABHA account, multiple OTP methods.
    2. Signup   -- no ABHA account yet; aegle_phr/phr/aadhaar_enrollment.py's
                   enrol_by_aadhaar() (M1's own Aadhaar-based enrollment).
    3. THIS MODULE -- already have an ABHA Number, want to create an ABHA
                   Address for it. A completely different operation from
                   Signup, not a follow-up step of it -- confirmed directly
                   against Aayush's own Postman collection's "Create ABHA
                   Address Flow" folder, which has THREE sub-flows: via
                   Mobile (identical to aegle_phr/phr/enrollment.py's
                   existing request_otp()/verify_otp(), scope
                   ["abha-address-enroll","mobile-verify"] -- untouched,
                   not part of this module), via "ABHA Number-Aadhaar OTP",
                   and via "ABHA Number-ABHA OTP" (mobile-based ownership
                   check against an ABHA Number rather than a raw mobile).
                   This module is the latter two -- verifying ownership of
                   an ALREADY-EXISTING ABHA Number, PHR spec SS3.4-SS3.10.

PHR spec SS3.4-SS3.10, straight from the Postman collection's own saved
request bodies (not guessed from a scope-name pattern):

    Via Aadhaar OTP (Postman: "Enrolment via ABHA Number-Aadhaar OTP"):
      request/otp: scope=["abha-login","aadhaar-verify"],
                   loginHint="abha-number", otpSystem="aadhaar"
      verify:      same scope, authData.otp{txnId, otpValue}

    Via ABHA/Mobile OTP (Postman: "Enrolment via ABHA Number-ABHA OTP"):
      request/otp: scope=["abha-login","mobile-verify"],
                   loginHint="abha-number", otpSystem="abdm"
      verify:      same scope, authData.otp{txnId, otpValue}

BOTH VARIANTS GO STRAIGHT FROM verify TO suggestion/isExists/enrol --
CORRECTED, 2026-08-31 (Aayush, directly): an earlier version of this
module added a verify/user step (POST {base}/phr/app/login/verify/user,
WITH a T-token, reusing aegle_phr/phr/login.py's own verify_user()) for
the mobile variant only, because the Postman collection's saved
"Enrolment via ABHA Number-ABHA OTP" folder happens to include one. That
step is not actually required in practice -- verify's own response
already carries everything needed to proceed (a full `accounts[]` array
with the complete demographic profile, confirmed live). Removed rather
than kept as an unused option. Lesson: a step existing in a reference
collection is not the same as a step being required.

CERTIFICATE, CORRECTED AFTER A LIVE FAILURE: settings.abdm_profile_certificate_url
(4096-bit), NOT settings.phr_certificate_url. The original version of this
module used phr_certificate_url, reasoning "same /phr/app/ URL prefix as
aegle_phr/phr/login.py's own request/otp+verify" -- that reasoning was
wrong. Live evidence: request_otp_via_aadhaar() with a placeholder ABHA
number and phr_certificate_url returned HTTP 400 {"code": "ABDM-9999",
"message": "Range [6, 0) out of bounds for length 0"} -- a raw Java-range-
exception leak, the signature of ABDM successfully receiving our ciphertext
but decrypting it into an empty string (a wrong-key symptom, not a
malformed-request one; a plaintext-loginId diagnostic on the SAME call
confirmed the request SHAPE was otherwise correct, returning the expected
"Invalid ABHA Number" format-check error instead). Switching to
abdm_profile_certificate_url on the SAME placeholder number changed the
result to {"code": "ABDM-9999", "message": "User not found"} -- a genuine,
specific business answer, meaning ABDM decrypted it successfully this
time. CONCLUSION: certificate choice tracks the SCOPE ("abha-login" here,
identity/profile-service business regardless of URL wrapper), not the URL
path prefix -- the same reasoning error may also explain the still-unresolved
P1-E "Invalid LoginId" mystery on aegle_phr/phr/login.py's OWN
request_abha_number_aadhaar_otp()/request_aadhaar_otp() (both scope=
"abha-login", both currently on phr_certificate_url, both blocked in that
investigation) -- flagged for whoever picks that investigation back up,
NOT fixed here (P1-E is explicitly a separate, on-hold investigation; this
chunk's own scope is P1-H only).

SUGGESTION/ISEXISTS/ENROL ARE NOT DUPLICATED HERE: once ownership is
verified, this flow needs exactly what aegle_phr/phr/enrollment.py's
address_suggestions()/address_exists()/enrol() already do -- confirmed
against the SAME Postman folder, whose "Suggestion API"/"isExists API"/
"Enroll ABHA Address" steps are byte-identical in shape to the ones
enrollment.py already implements for its own mobile-enrollment flow. The
demographics (name, DOB, gender, address, mobile) are typed by the user
here, same as enrollment.py's own flow -- unlike Signup, this flow has no
Aadhaar e-KYC data to auto-fill from; ABDM's verify response for an
ownership check does not hand back a profile the way enrol_by_aadhaar's
does.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.settings import Settings

# PHR spec SS3.4-SS3.7's own scopes -- used identically for request/otp and verify.
ABHA_NUMBER_AADHAAR_VERIFY_SCOPE = ["abha-login", "aadhaar-verify"]
ABHA_NUMBER_MOBILE_VERIFY_SCOPE = ["abha-login", "mobile-verify"]

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class AbdmResult:
    status_code: int | None
    body: Any
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
    }


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PROFILE certificate -- see module banner for why THIS certificate, confirmed live."""
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _execute(
    route: str,
    url: str,
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
    retry: bool = True,
    extra_response_secrets: Callable[[Any], tuple[str, ...]] | None = None,
) -> AbdmResult:
    """
    extra_response_secrets: REDACTION GAP FIX, same reasoning as aegle_phr/
        phr/login.py's own parameter of this name -- verify's response
        (confirmed live, 2026-08-31) nests plaintext mobile/email inside an
        `accounts[]` array, a shape not knowable before the call returns.
        "mobile" and "email" are both in redaction.py's _CIPHERTEXT_SAFE_PATHS
        (needed elsewhere, where those keys hold ciphertext), so the
        key-based rule alone would NOT catch them here -- this callback
        lets the caller name the actual plaintext values found in the
        parsed response, merged into plaintext_secrets before archiving so
        the value-based scrub (which ignores that exemption) still gets them.
    """
    headers = _headers()
    started = time.monotonic()

    def attempt() -> requests.Response:
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    try:
        if retry:
            response = call_with_retry(attempt, description=description)
        else:
            response = call_with_retry(
                attempt, description=description, is_transient=lambda r, e: False, max_attempts=1
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


def _account_plaintext_fields(body: Any, *field_names: str) -> tuple[str, ...]:
    """
    Pulls named string fields out of every entry in a response's
    `accounts[]` list, if present -- the confirmed real shape of this
    flow's own verify response (not a top-level field, unlike login.py's
    _plaintext_string_fields(), which this otherwise mirrors).
    """
    if not isinstance(body, dict):
        return ()
    accounts = body.get("accounts")
    if not isinstance(accounts, list):
        return ()
    found = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        for name in field_names:
            value = account.get(name)
            if isinstance(value, str) and value != "":
                found.append(value)
    return tuple(found)


# ---------------------------------------------------------------------------
# Via Aadhaar OTP  (SS3.4-SS3.5)
# ---------------------------------------------------------------------------

def request_otp_via_aadhaar(settings: Settings, abha_number: str) -> AbdmResult:
    """Sends a REAL OTP via UIDAI, to verify ownership of an EXISTING ABHA Number. Never retried."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/request/otp"
    payload = {
        "scope": ABHA_NUMBER_AADHAAR_VERIFY_SCOPE,
        "loginHint": "abha-number",
        "loginId": _encrypt(settings, abha_number),
        "otpSystem": "aadhaar",
    }
    log_phase("Requesting ABHA Address creation OTP via Aadhaar (real OTP)")
    return _execute(
        route="/phr/abha-address/request-otp-aadhaar",
        url=url,
        payload=payload,
        description="ABHA Address creation ownership-verify OTP request (Aadhaar)",
        plaintext_secrets=(abha_number,),
        retry=False,
    )


def verify_otp_via_aadhaar(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    Goes straight from here to suggestion/isExists/enrol -- no verify/user
    step. Response confirmed live to carry a full `accounts[]` array with
    the complete demographic profile (see the frontend's own extractAccount()).
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/verify"
    payload = {
        "scope": ABHA_NUMBER_AADHAAR_VERIFY_SCOPE,
        "authData": {
            "authMethods": ["otp"],
            "otp": {"txnId": txn_id, "otpValue": _encrypt(settings, otp)},
        },
    }
    log_phase("Verifying ABHA Address creation OTP via Aadhaar")
    return _execute(
        route="/phr/abha-address/verify-otp-aadhaar",
        url=url,
        payload=payload,
        description="ABHA Address creation ownership-verify OTP verify (Aadhaar)",
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _account_plaintext_fields(body, "mobile", "email", "emailVerified"),
    )


# ---------------------------------------------------------------------------
# Via ABHA/Mobile OTP  (SS3.6-SS3.7)
# ---------------------------------------------------------------------------

def request_otp_via_mobile(settings: Settings, abha_number: str) -> AbdmResult:
    """Sends a REAL SMS to the mobile linked to this ABHA Number. Never retried."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/request/otp"
    payload = {
        "scope": ABHA_NUMBER_MOBILE_VERIFY_SCOPE,
        "loginHint": "abha-number",
        "loginId": _encrypt(settings, abha_number),
        "otpSystem": "abdm",
    }
    log_phase("Requesting ABHA Address creation OTP via mobile (real SMS)")
    return _execute(
        route="/phr/abha-address/request-otp-mobile",
        url=url,
        payload=payload,
        description="ABHA Address creation ownership-verify OTP request (mobile)",
        plaintext_secrets=(abha_number,),
        retry=False,
    )


def verify_otp_via_mobile(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    Goes straight from here to suggestion/isExists/enrol, same as the
    Aadhaar variant -- no verify/user step (removed, see module banner:
    the Postman collection's own saved example has one, but it is not
    actually required in practice).
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/verify"
    payload = {
        "scope": ABHA_NUMBER_MOBILE_VERIFY_SCOPE,
        "authData": {
            "authMethods": ["otp"],
            "otp": {"txnId": txn_id, "otpValue": _encrypt(settings, otp)},
        },
    }
    log_phase("Verifying ABHA Address creation OTP via mobile")
    return _execute(
        route="/phr/abha-address/verify-otp-mobile",
        url=url,
        payload=payload,
        description="ABHA Address creation ownership-verify OTP verify (mobile)",
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _account_plaintext_fields(body, "mobile", "email", "emailVerified"),
    )
