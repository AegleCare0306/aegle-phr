"""
PHR-side wrapper around abdm_core.email_verification (P1-F, added by
Aayush's request alongside the Aadhaar enrollment work). Sends a REAL
email containing a clickable verification link -- fire and forget, no
verify/OTP step exists for this call anywhere in this project's reference
code (see abdm_core.email_verification's own banner).

REQUIRES AN X-TOKEN: unlike every OTP-based call elsewhere in this
project, this is a POST-registration "link email to my now-authenticated
account" action. SETTLED, confirmed live 2026-08-31 (Aayush tested
directly): the caller's session token IS enrol_by_aadhaar's own
(tokens.token) -- despite that token being transaction-scoped and
confirmed rejected by mobile-linking's own endpoints, it IS accepted
here. See abdm_core.email_verification's own banner for the full
back-and-forth on this (two corrections, settled on the original
answer) -- don't re-derive "transaction-scoped" into "universally
invalid" again. Also reachable via a session from logging in separately
(e.g. Mobile OTP login) -- password is a login mechanism, not part of
registration, so no registration-flow response other than the above is
assumed to grant one.

CERTIFICATE: the PROFILE certificate (settings.abdm_profile_certificate_url),
same one aadhaar_enrollment.py uses -- inferred from the one confirmed
call site (repo/tools/m1_test_suite/flows/profile_utilities.py's
_link_email(), via its own common.py encrypt() with no certificate URL
override), NOT independently re-confirmed against ABDM's own spec for
this specific endpoint. Flagged in abdm_core.email_verification's own
banner too -- worth re-checking if this call ever fails with a
generic/mysterious decrypt-shaped error the way a wrong certificate
would.
"""

import time
from dataclasses import dataclass
from typing import Any

from abdm_core.email_verification import request_email_verification_link as _abdm_request_email_link
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
    """RSA-OAEP against the PROFILE certificate -- see module banner."""
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


def _parse(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def request_email_verification_link(settings: Settings, x_token: str, email: str) -> AbdmResult:
    """Sends a REAL email. No follow-up call exists for this flow -- see module banner."""
    log_phase("Requesting email verification link (real email)")
    login_id = _encrypt(settings, email)
    route = "/phr/profile/request-email-verification-link"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/profile/account/request/emailVerificationLink"
    started = time.monotonic()

    try:
        response, payload = _abdm_request_email_link(settings.abdm_abha_base_url, x_token, login_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Email verification link request failed: {exc}")
        archive(route, url, {"loginId": login_id}, None, None, duration_ms, str(exc), (email,))
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)
    archive(route, url, payload, response.status_code, body, duration_ms, None, (email,))
    return AbdmResult(status_code=response.status_code, body=body)
