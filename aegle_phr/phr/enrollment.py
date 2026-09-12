"""
ABHA address registration via mobile number -- the five ABDM calls.

One function per call. Each returns an AbdmResult carrying the HTTP status
and the RAW parsed body, and each archives itself to abdm_call_log.

=============================================================================
UNDOCUMENTED RESPONSE SHAPES -- READ BEFORE ADDING A RESPONSE MODEL
=============================================================================
ABDM's specification gives complete REQUEST bodies for all five calls but
leaves the "Response Body" section EMPTY for:

    /phr/app/enrollment/verify
    /phr/app/enrollment/suggestion
    /phr/app/enrollment/enrol

This is a gap in the document, confirmed, not something overlooked here.

So none of those three has a Pydantic response model, and nothing in this
module reads a field out of them. They are returned and stored verbatim, and
the first real sandbox run is what tells us the shape. Inventing a model
here would turn a documentation gap into a silent parsing bug.

The only documented response shape is request/otp's ({txnId, message}) --
see RequestOtpResponse below. Even that is returned raw; the model exists to
record what is specified, not to gate the response.
=============================================================================

ENCRYPTION: mobile, otpValue and password are RSA-encrypted against the PHR
certificate at settings.phr_certificate_url -- NOT the /profile/public/
certificate endpoint the sibling HIP/HIU repo uses. Measured 2026-08-27:
those two endpoints serve genuinely different keys (2048-bit vs 4096-bit).
Using the wrong one produces ciphertext ABDM cannot decrypt, and the failure
surfaces much later as a generic error.
"""

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.settings import Settings

# The scope pair used by every call in the mobile registration path.
MOBILE_ENROL_SCOPE = ["abha-address-enroll", "mobile-verify"]

_TIMEOUT_SECONDS = 30


class RequestOtpResponse(BaseModel):
    """
    The ONE documented response shape in this flow (call 1).

    Not used to validate or gate anything -- the route returns the raw body.
    It exists so the documented contract is written down somewhere in code.
    """

    txnId: str
    message: str


@dataclass(frozen=True)
class AbdmResult:
    """Status plus the raw parsed body. No interpretation."""

    status_code: int | None
    body: Any
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def _never_transient(response: Any, exception: Any) -> bool:
    """
    Classifier for the OTP request: NOTHING is retryable.

    Chosen over skipping call_with_retry entirely so every call in this
    module goes through one code path -- but the effect is a single
    attempt, always. Retrying an OTP request is not a harmless repeat: each
    attempt sends a real SMS and counts toward ABDM's own limits
    (ABDM-1100 locks the transaction for 30 minutes; ABDM-1027 locks the
    CLIENT for 24 hours). A transient-looking 5xx is not worth that risk,
    because we cannot tell from a failed response whether the SMS was sent
    before the failure.
    """
    return False


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
    }


def _parse(response: requests.Response) -> Any:
    """
    Parsed JSON when possible, raw text otherwise.

    isExists returns a bare `true` -- a scalar, not an object -- so nothing
    here may assume a dict. Callers get whatever came back.
    """
    try:
        return response.json()
    except ValueError:
        return response.text


def _execute(
    route: str,
    method: str,
    url: str,
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
    retry: bool = True,
) -> AbdmResult:
    """
    Performs one ABDM call, archives it, and returns the raw result.

    Never calls raise_for_status(): a 400 from ABDM ("wrong OTP", "address
    taken") is an expected, handled outcome for this flow, not an
    exception. Callers inspect status_code themselves.
    """
    headers = _headers()
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

    log_api_call(description, url, response.status_code)
    archive(route, url, payload, response.status_code, body, duration_ms, None, plaintext_secrets)

    return AbdmResult(status_code=response.status_code, body=body)


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PHR certificate. Never log the input."""
    public_key = get_public_certificate(settings.phr_certificate_url)
    return encrypt_value(value, public_key)


# ---------------------------------------------------------------------------
# 1. Request OTP  --  POST /phr/app/enrollment/request/otp
# ---------------------------------------------------------------------------

def request_otp(settings: Settings, mobile: str) -> AbdmResult:
    """
    Sends a REAL SMS. Never retried -- see _never_transient().

    Documented response: 200 with {"txnId": "...", "message": "OTP is sent
    to Mobile number ending with ******2425"}.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/request/otp"

    payload = {
        "scope": MOBILE_ENROL_SCOPE,
        "loginHint": "mobile-number",
        "loginId": _encrypt(settings, mobile),
        "otpSystem": "abdm",
    }

    log_phase("Requesting enrollment OTP (real SMS)")
    return _execute(
        route="/phr/enrollment/request-otp",
        method="POST",
        url=url,
        payload=payload,
        description="PHR enrollment OTP request",
        plaintext_secrets=(mobile,),
        retry=False,
    )


# ---------------------------------------------------------------------------
# 2. Verify OTP  --  POST /phr/app/enrollment/verify
# ---------------------------------------------------------------------------

def verify_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    RESPONSE SHAPE UNDOCUMENTED. The prose says it returns a success
    message plus any ABHA address already linked to that mobile; the
    document's Response Body section is empty. Returned verbatim.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/verify"

    payload = {
        "scope": MOBILE_ENROL_SCOPE,
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "txnId": txn_id,
                "otpValue": _encrypt(settings, otp),
            },
        },
    }

    log_phase("Verifying enrollment OTP")
    # Retried on transient failures only. The OTP is single-use, so a retry
    # after ABDM has already consumed it would fail -- but call_with_retry
    # only retries connection errors/timeouts and 5xx/429/408, never a
    # normal "wrong OTP" response, so a consumed OTP is not re-submitted
    # after a successful HTTP exchange. UNCONFIRMED: whether ABDM consumes
    # the OTP on a request that then 5xx's. Flagged, not assumed.
    return _execute(
        route="/phr/enrollment/verify-otp",
        method="POST",
        url=url,
        payload=payload,
        description="PHR enrollment OTP verify",
        plaintext_secrets=(otp,),
    )


# ---------------------------------------------------------------------------
# 3. Address suggestions  --  POST /phr/app/enrollment/suggestion
# ---------------------------------------------------------------------------

def address_suggestions(
    settings: Settings,
    txn_id: str,
    first_name: str,
    last_name: str,
    day_of_birth: str,
    month_of_birth: str,
    year_of_birth: str,
    email: str | None = None,
) -> AbdmResult:
    """
    RESPONSE SHAPE UNDOCUMENTED.

    CONTRADICTION IN THE SPEC: the parameter table lists `email` as
    REQUIRED, but the example request body omits it entirely. Resolved by
    sending it only when the caller supplies one, and recording what
    happens -- so the live run answers which half of the document is right.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/suggestion"

    payload: dict[str, Any] = {
        "txnId": txn_id,
        "firstName": first_name,
        "lastName": last_name,
        "dayOfBirth": day_of_birth,
        "monthOfBirth": month_of_birth,
        "yearOfBirth": year_of_birth,
    }
    if email:
        payload["email"] = email

    log_phase(f"Requesting ABHA address suggestions (email {'sent' if email else 'omitted'})")
    return _execute(
        route="/phr/enrollment/suggestions",
        method="POST",
        url=url,
        payload=payload,
        description="PHR ABHA address suggestions",
    )


# ---------------------------------------------------------------------------
# 4. Address availability  --  GET /phr/app/enrollment/isExists
# ---------------------------------------------------------------------------

def address_exists(settings: Settings, abha_address: str) -> AbdmResult:
    """
    Returns a BARE boolean -- a JSON scalar, not an object. _parse()
    handles that; nothing here indexes into the body.

    POLARITY, CONFIRMED BY EXPERIMENT 2026-08-27 -- read this before
    renaming anything back:

        true  = the address EXISTS, i.e. it is TAKEN
        false = the address does not exist, i.e. it is FREE to register

    The endpoint name says exactly this, but the specification presents it
    under an availability heading and only ever shows the `true` case,
    which reads naturally as "yes, available". It is the opposite.
    Verified by calling it twice in one run: a freshly suggested address
    returned false, and an address already known to exist (from
    /verify's own users list) returned true.

    An earlier version of this function was called address_available(),
    which inverted the meaning for every caller. Everything downstream --
    the route path, the API response field and the UI copy -- now says
    "exists"/"taken" so the boolean cannot be misread.
    """
    base = settings.abdm_abha_base_url.rstrip("/")
    url = f"{base}/phr/app/enrollment/isExists?abhaAddress={quote(abha_address, safe='')}"

    log_phase(f"Checking whether ABHA address already exists: {abha_address}")
    return _execute(
        route="/phr/enrollment/address-exists",
        method="GET",
        url=url,
        payload=None,
        description="PHR ABHA address existence check",
    )


# ---------------------------------------------------------------------------
# 5. Enrol  --  POST /phr/app/enrollment/enrol
# ---------------------------------------------------------------------------

def enrol(
    settings: Settings,
    txn_id: str,
    mobile: str,
    abha_address: str,
    password: str,
    phr_details: dict[str, str],
) -> AbdmResult:
    """
    RESPONSE SHAPE UNDOCUMENTED -- and in particular it is NOT known
    whether this returns the patient's X-token / any session token. That
    answer determines whether P2 needs a separate login step after
    registration, so the live run must capture the full body.

    ABHANumber and profilePhoto appear in one spec example and not others;
    both are treated as optional and are simply not sent here.

    Args:
        phr_details: The plaintext demographic fields (names, DOB, gender,
            address, state/district, pincode). Passed through as-is --
            ABDM expects these unencrypted. mobile, password, and (when
            non-empty) email are encrypted.

    EMAIL ENCRYPTION, CONFIRMED LIVE 2026-08-31 (Aayush): every reference
    example of this endpoint's request body (this project's own captures
    and Aayush's Postman collection) shows `email: ""` -- blank, never a
    populated value -- so the correct format for a non-blank email was
    never actually confirmed by any reference. A real address sent as
    plain text failed live with ABDM-1006 "Invalid Email"; the same
    request with the email RSA-encrypted (same treatment as mobile/
    password) succeeded. Only encrypted when non-empty -- an empty string
    is sent as-is, matching the one shape every reference example shows.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/enrollment/enrol"

    email = phr_details.get("email", "")

    details: dict[str, Any] = {
        "mobile": _encrypt(settings, mobile),
        "firstName": phr_details.get("firstName", ""),
        "middleName": phr_details.get("middleName", ""),
        "lastName": phr_details.get("lastName", ""),
        "dayOfBirth": phr_details.get("dayOfBirth", ""),
        "monthOfBirth": phr_details.get("monthOfBirth", ""),
        "yearOfBirth": phr_details.get("yearOfBirth", ""),
        "gender": phr_details.get("gender", ""),
        "email": _encrypt(settings, email) if email else "",
        "address": phr_details.get("address", ""),
        "stateName": phr_details.get("stateName", ""),
        "stateCode": phr_details.get("stateCode", ""),
        "districtName": phr_details.get("districtName", ""),
        "districtCode": phr_details.get("districtCode", ""),
        "pinCode": phr_details.get("pinCode", ""),
        "abhaAddress": abha_address,
        "password": _encrypt(settings, password),
    }

    payload = {"txnId": txn_id, "phrDetails": details}

    log_phase(f"Enrolling ABHA address {abha_address}")
    return _execute(
        route="/phr/enrollment/enrol",
        method="POST",
        url=url,
        payload=payload,
        description="PHR ABHA address enrolment",
        plaintext_secrets=(mobile, password, email),
    )
