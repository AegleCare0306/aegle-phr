"""
Mobile linking, chained off a FRESH Aadhaar-based enrollment (P1-J,
corrected after two live failures) -- PHR-side wrapper around
abdm_core.aadhaar_enrollment's request_mobile_link_otp()/
verify_mobile_link_otp(), which port M1 test suite Flow 10
(repo/tools/m1_test_suite/flows/link_mobile.py) directly.

CORRECTED, NOT THE ORIGINAL VERSION: this module used to target the PHR
spec's own "abha-address-profile" scope family (/phr/app/login/profile/...,
requiring a real logged-in X-token) -- confirmed live to fail with
"Invalid X-token", because a fresh enrol/byAadhaar's own session token is
transaction-scoped ("typ": "Transaction" in its own JWT), not a real
account session. M1's OWN Flow 10 solves this differently: it chains
DIRECTLY off the SAME "action=enrollment" transaction family Aadhaar
enrollment itself uses, needing no X-token and no separate login at all.
See abdm_core.aadhaar_enrollment's own banner for the full correction.

CERTIFICATE: settings.abdm_profile_certificate_url -- this hits
/enrollment/... (no "/phr/app/" prefix), the SAME URL family
aadhaar_enrollment.py's own enrol_by_aadhaar() uses, and that module
already correctly uses the profile certificate. NOT phr_certificate_url
-- that one is for the /phr/app/... family (mobile OTP login, all five
P1-E methods), a genuinely different URL family from this one.

request_otp() NEEDS THE ORIGINAL ENROLLMENT txnId (corrected, confirmed
live 2026-08-31): M1's own Flow 10 sends "txnId": "" here (a literal
reading of link_mobile.py's call to request_login_otp(), which defaults
txn_id to ""). Tried that first -- ABDM rejected it live with HTTP 400
{"txnId": "Invalid Transaction Id"} on this scope, moments after the
SAME shared function's txnId="" was accepted fine for the plain
scope=["abha-enrol"] enrollment OTP request. See
abdm_core.aadhaar_enrollment.request_mobile_link_otp()'s own docstring
for the full reasoning -- passing the original enrollment txnId here
matches what create_abha_address()/get_address_suggestions() already do.
"""

import time
from dataclasses import dataclass
from typing import Any

from abdm_core.aadhaar_enrollment import (
    request_mobile_link_otp as _abdm_request_otp,
    verify_mobile_link_otp as _abdm_verify_otp,
)
from abdm_core.observability.flow_logger import log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate

from aegle_phr.phr.call_log import archive
from aegle_phr.settings import Settings


@dataclass(frozen=True)
class AbdmResult:
    status_code: int | None
    body: Any
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PROFILE certificate -- see module banner for why THIS certificate."""
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


def _parse(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def request_otp(settings: Settings, txn_id: str, mobile: str) -> AbdmResult:
    """
    Sends a REAL SMS. Default retry classifier, matching repo/server/
    abha.py's own request_otp(). `txn_id` is the ORIGINAL enrollment
    transaction's id, NOT a fresh/blank one -- see module banner.
    """
    log_phase("Requesting mobile-linking OTP (real SMS)")
    login_id = _encrypt(settings, mobile)
    route = "/phr/profile/link-mobile/request-otp"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/request/otp"
    started = time.monotonic()

    try:
        response, payload = _abdm_request_otp(settings.abdm_abha_base_url, txn_id, login_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Mobile linking OTP request failed: {exc}")
        archive(route, url, {"loginId": login_id}, None, None, duration_ms, str(exc), (mobile,))
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, (mobile,))
    return AbdmResult(status_code=response.status_code, body=body)


def verify_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    Documented success (M1's own confirmed shape): {message, ABHANumber,
    ...}. Returned raw regardless; not assumed correct until re-checked.
    """
    log_phase("Verifying mobile-linking OTP")
    otp_ciphertext = _encrypt(settings, otp)
    route = "/phr/profile/link-mobile/verify-otp"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/enrollment/auth/byAbdm"
    started = time.monotonic()

    try:
        response, payload = _abdm_verify_otp(settings.abdm_abha_base_url, txn_id, otp_ciphertext)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Mobile linking OTP verify failed: {exc}")
        archive(route, url, {"txnId": txn_id}, None, None, duration_ms, str(exc), (otp,))
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, (otp,))
    return AbdmResult(status_code=response.status_code, body=body)
