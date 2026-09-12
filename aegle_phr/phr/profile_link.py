"""
Link/De-link ABHA Number, Switch Profile, QR Code, PHR Card, and Refresh
Token (P1-N) -- finishes the PHR spec's own "PHR_Profile" section
(SS3.31-SS3.43) that P1-M didn't cover. Same URL family as profile.py
(/phr/app/login/profile/...), same certificate (settings.phr_certificate_url,
2048-bit) for every field EXCEPT everything inside Link/De-link's own
"abha-login" scope (both the loginId in request/otp AND the otpValue in
verify) -- see _encrypt_abha_login()'s own docstring below for a THIRD
correction this project has now had to make to the "judge cert by URL
family" rule (P1-G->P1-J, then P1-N's own first pass, now this): the rule
holds for mobile/email/password, but the "abha-login" scope family is its
own exception, confirmed live here and previously by a different chunk
(abha_address_creation.py, P1-H) hitting the identical thing.

A SIBLING MODULE, NOT AN ADDITION TO profile.py: profile.py is already
sizeable; this duplicates the small _headers()/_encrypt()/_execute() shape
rather than importing profile.py's private functions across modules,
matching this project's existing per-module-helper convention (see
login.py's own banner on why enrollment.py's near-identical plumbing
wasn't factored out either). ONE STRUCTURAL DIFFERENCE FROM profile.py's
OWN _execute(): this module's takes pre-built `headers` rather than an
`x_token` it builds headers from internally -- needed because three
DIFFERENT header builders exist below (X-Token/T-token/R-token) and a
single call site picks whichever one a given endpoint needs.

THREE DIFFERENT SESSION-TOKEN HEADERS IN THIS ONE MODULE -- don't default
to one everywhere:
  - X-Token -- every call except the two named below.
  - T-token -- Switch-Profile-VERIFY only (spec SS3.38, confirmed by both
    spec and live Postman -- the REQUEST step above it still uses
    X-Token; only verify differs). Matches this project's own T-token
    precedent (login.py's verify_user()).
  - R-token -- Refresh Token only (spec SS3.43).
Authorization (gateway token) is still sent alongside every one of these
three -- same "send both, cheapest safe default" reasoning profile.py's
own banner already established for X-Token.

LINK ABHA NUMBER (SS3.31-3.36): loginHint is ALWAYS "abha-number" for
BOTH sub-methods (Mobile-OTP and Aadhaar-OTP) -- loginId is the ABHA
NUMBER being linked, not a mobile/Aadhaar value; what differs between the
two sub-methods is only `scope`/`otpSystem` (mobile: ["abha-login",
"mobile-verify"]/"abdm"; Aadhaar: ["abha-login","aadhaar-verify"]/
"aadhaar") and which OTP channel ABDM actually uses to deliver the code
(whichever mobile/Aadhaar is on file for that ABHA number -- not
something this module controls). Live Postman confirms the verify
response's `users[]` uses lowercase `abhaNumber` while `accounts[]` uses
PascalCase `ABHANumber` -- the SAME response, different casing for the
same concept in two different arrays. NOT normalized away here -- this
module returns the raw body untouched, same convention as every other
call in this project; a caller reading either array must accept both
spellings defensively (mirroring first_present()'s pattern, e.g. M1's
profile_utilities.py). ALSO CONFIRMED: a wrong/expired OTP can come back
as HTTP 200 with authResult: "failed" and empty users: [] -- a caller
must check authResult, not just status_code, same lesson this project's
login flows already learned.

DE-LINK -- A HYPOTHESIS, FLAGGED, NOT PROVEN: no saved Postman example
exists for a working de-link call anywhere in the collection (a full-text
search of the entire ~2.5M-character export found only "action": "LINK"
everywhere, plus one saved ERROR example named "Link Request - Invalid
Account Action" implying the endpoint validates `action` against an
allowed set that presumably includes DELINK). process_link() below
accepts `action` as a plain string rather than hardcoding "LINK", so a
caller can pass "DELINK" -- built this way, but genuinely unverified
until a live call either confirms it or returns something other than the
confirmed LINK success shape or "Invalid Account Action" -- in which
case: report the raw error and STOP, don't guess further (no alternate
field names, no alternate endpoints).

SWITCH PROFILE (SS3.37-3.38): the request step's response has no
documented body in the spec (blank) -- a real saved Postman example
(343KB) fills the gap: `txnId` + `users[]` (real ABHA profiles for the
account, heterogeneous -- fullName/status/kycStatus/profilePhoto
inconsistently present, not a clean template) + `tokens` (expiresIn: 300,
refreshToken: null -- this project's own established "transient token"
shape, e.g. verify_user()'s T-token). `tokens.token` from THIS response
is the T-token verify_switch_profile() needs. The verify step's response
is a BARE top-level `token`/`expiresIn`/`refreshToken` -- NOT nested
under `tokens{}` like every other verify-style response in this project;
testui's session.ts has a SEPARATE extractor for this shape
(extractBareSessionToken()) rather than forcing it through the existing
one. The spec's own gating rule ("If a user logs in using an ABHA
Address, they will not be able to switch between different users...") is
enforced in testui (ProfileScreen.tsx, via session.ts's own
getLoginMethod()/canSwitchProfile()), not here -- this module has no
concept of how the session was established, same "UI/editability
concern, not something this backend module enforces" pattern profile.py
already established for the eKYC-lock rule.

QR CODE / PHR CARD (SS3.40/3.41) -- BINARY-SAFE, NOT JSON-ASSUMED: the
spec labels both "202 Accepted" and each has only a placeholder saved
Postman example (`"QR Code"` / `"PHR Card"`, literal 7/8-character
strings, NOT real payload data) -- the real live Content-Type/body shape
is UNCONFIRMED until run live. Mirrors abha_card.py's own base64+
Content-Type approach (not imported from it -- different URL family, and
the task prompt explicitly says don't touch/reuse that module -- but the
SAME pattern: read response.content/headers directly, base64-encode for
this app's JSON-only API surface, never call .json() unconditionally).
PHR Card (SS3.41) is explicitly a DIFFERENT card from the ABHA card
abha_card.py already fetches (P1-L, /profile/account/abha-card, needs
both ABHA number AND address, chained off a fresh Aadhaar-enrollment
token) -- this one needs only an address, on a real logged-in session,
different URL family (/phr/app/login/profile/phrCard), different
certificate. Not touched, not reused; a new, parallel capability.

REFRESH TOKEN (SS3.43): GET, no request body (the spec's own property
table for this section -- status/consentId/error/requestId -- is a
copy-paste leftover from a different endpoint and is ignored here, not
implemented). Response: {"tokens": {"token", "expiresIn": 1800,
"refreshToken", "refreshExpiresIn": 1296000}} -- WRAPPED under `tokens`,
unlike Switch-Profile-Verify's bare shape above; session.ts's EXISTING
extractSessionToken() (the tokens{}-wrapped one) is the right reader for
THIS response, not the new bare one. Live Postman's saved example shows
refreshToken: "" (empty) -- whether the real API rotates the refresh
token or always returns it empty is UNCONFIRMED; this module returns
whatever comes back, unfiltered -- a caller that gets an empty string
back simply doesn't replace its stored refresh token (session.ts's
setSession() already treats an empty/absent refreshToken as "leave
whatever's there alone").

RETRY: request/otp calls (Link/De-link's own OTP send) are NEVER
retried, same real-SMS/real-OTP reasoning as every other OTP request in
this project. Every verify call uses the DEFAULT classifier, matching
profile.py's own verify_update_mobile_otp()/verify_update_email_otp()/
login.py's verify_user() precedent (a resubmitted attempt after a
transient failure is a structurally identical risk already accepted
elsewhere in this project). process_link()/refresh_token()/
get_qr_code()/get_phr_card()/request_switch_profile() are all
read-only-or-idempotent -- default classifier.

REDACTION: OTP values are already covered by redaction.py's existing
"otpvalue" key-based rule; nothing new needed there. The ABHA NUMBER
being linked (loginId, always sent ENCRYPTED here, never plaintext in
any outbound payload this module builds) is not itself flagged as a
secret -- an ABHA Number is an account identifier, not PII in the same
class as a raw Aadhaar number, mobile, or password; this mirrors how
abhaAddress/abhaNumber already appear unredacted elsewhere in this
project's archived request bodies (e.g. every login flow's own payload).
Switch Profile's chosen abhaAddress is likewise not redacted, same
reasoning. NOT COVERED, FLAGGED RATHER THAN SILENTLY FIXED (matches
aadhaar_enrollment.py's own precedent for enrol_by_aadhaar()'s
undocumented photo field): Link/De-link's verify response nests
profilePhoto AND kycPhoto inside `accounts[]`, and Switch Profile's own
`users[]` entries often carry a profilePhoto too -- this project's
existing `_plaintext_string_fields()`-style defensive check (used below
for top-level mobile/email, same as profile.py) does not reach INTO
nested array entries, so a live run of this chunk's own calls will store
those base64 photos in abdm_call_log in plaintext. This is the same
already-accepted limitation this project's redaction has had since
P1-F, not a new gap this chunk introduces -- flagged again here because
this chunk's own responses are the richest example of it yet.
"""

import base64
import time
from typing import Any, Callable

import requests
from dataclasses import dataclass

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.rsa_crypto import encrypt_value, get_public_certificate
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

MOBILE_LINK_SCOPE = ["abha-login", "mobile-verify"]
AADHAAR_LINK_SCOPE = ["abha-login", "aadhaar-verify"]

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class BinaryResult:
    """Same shape as abha_card.py's own AbhaCardResult -- duplicated, not imported (different URL family, kept as a separate, parallel module)."""

    status_code: int | None
    content_type: str | None
    base64_body: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def _headers(x_token: str) -> dict[str, str]:
    """Every call in this module EXCEPT Switch-Profile-Verify and Refresh Token -- see module banner."""
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-Token": f"Bearer {x_token}",
    }


def _headers_t_token(t_token: str) -> dict[str, str]:
    """Switch-Profile-Verify ONLY -- see module banner."""
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "T-token": f"Bearer {t_token}",
    }


def _headers_r_token(r_token: str) -> dict[str, str]:
    """Refresh Token ONLY -- see module banner. No Content-Type: GET, no body."""
    return {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "R-token": f"Bearer {r_token}",
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
    headers: dict[str, str],
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
    extra_response_secrets: Callable[[Any], tuple[str, ...]] | None = None,
    retry: bool = True,
) -> AbdmResult:
    """Performs one ABDM call, archives it, returns the raw result. Never calls raise_for_status() -- see enrollment.py's own _execute() for why."""
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


def _execute_binary(route: str, url: str, headers: dict[str, str], description: str) -> BinaryResult:
    """QR Code / PHR Card -- never calls .json(); base64-encodes raw bytes. See module banner's QR CODE / PHR CARD section."""
    started = time.monotonic()
    try:
        response = call_with_retry(
            lambda: requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS), description=description
        )
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, {}, None, None, duration_ms, str(exc), ())
        return BinaryResult(status_code=None, content_type=None, base64_body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    succeeded = 200 <= response.status_code < 300
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip() or None
    body_b64 = base64.b64encode(response.content).decode("ascii") if succeeded else None
    archived_body: Any = {"contentType": content_type, "base64Length": len(body_b64)} if body_b64 else response.text
    archive(route, url, {}, response.status_code, archived_body, duration_ms, None, ())
    return BinaryResult(status_code=response.status_code, content_type=content_type, base64_body=body_b64)


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PHR certificate -- see module banner for why THIS certificate, not the profile one. NOT used anywhere in the abha-login scope family (Link/De-link) -- see _encrypt_abha_login()."""
    public_key = get_public_certificate(settings.phr_certificate_url)
    return encrypt_value(value, public_key)


def _encrypt_abha_login(settings: Settings, value: str) -> str:
    """
    CORRECTED (confirmed live 2026-09-01: Aayush hit "Invalid LoginId" /
    ABDM-1006 on Link ABHA Number's request/otp using the ordinary
    _encrypt() (PHR certificate) for the loginId; switching this one field
    to the PROFILE certificate fixed it, confirmed live). Renamed from an
    earlier, narrower _encrypt_abha_number() once the SAME reasoning was
    applied to the verify step's otpValue too (see below) -- this isn't
    really about "encrypting an ABHA number" specifically, it's about
    encrypting ANYTHING inside the "abha-login" scope family.

    THE ACTUAL RULE, established earlier by a DIFFERENT chunk
    (abha_address_creation.py's own banner, P1-H, confirmed by a live
    before/after test there): certificate choice tracks the SCOPE --
    specifically, whether "abha-login" is in it -- not the URL path
    prefix, and not which field is being encrypted. MOBILE_LINK_SCOPE/
    AADHAAR_LINK_SCOPE both contain "abha-login", so BOTH the loginId in
    _request_link_otp() AND the otpValue in _verify_link_otp() use this,
    not the module's ordinary _encrypt(). The verify-step half of this
    was applied proactively, from the established rule, BEFORE hitting a
    live failure on it -- confirm it holds the same way request/otp's fix
    already did, and report back if it doesn't.

    Confirmed by the M1 CLI's own working precedent for a DIFFERENT
    feature that also encrypts an ABHA Number as loginId --
    repo/tools/m1_test_suite/flows/login_abha_number.py (ABHA-Number-
    based LOGIN, not Link) -- whose common.py encrypt() call has NO
    certificate override, defaulting to exactly this profile endpoint
    (same default aadhaar_enrollment.py's own enrol_by_aadhaar() relies
    on). This also almost certainly explains a previously-flagged,
    never-root-caused mystery, independently documented TWICE now
    (abha_address_creation.py's own banner, and again here): aegle_phr/
    phr/login.py's own request_abha_number_aadhaar_otp()/
    request_abha_number_mobile_otp()/request_aadhaar_otp() (scope
    "abha-login", all on phr_certificate_url) almost certainly have the
    identical bug -- NOT fixed here, out of this module's scope, but
    flagged a third time for whoever picks that up next.
    """
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


def _plaintext_string_fields(body: Any, *field_names: str) -> tuple[str, ...]:
    """Mirrors profile.py's/login.py's own helper of the same name -- duplicated, not imported. TOP-LEVEL keys only -- see module banner's REDACTION section for the nested-array limitation this shares with the rest of this project."""
    if not isinstance(body, dict):
        return ()
    found = []
    for name in field_names:
        value = body.get(name)
        if isinstance(value, str) and value != "":
            found.append(value)
    return tuple(found)


# ---------------------------------------------------------------------------
# Link / De-link ABHA Number -- SS3.31-3.36
# ---------------------------------------------------------------------------

def _request_link_otp(
    settings: Settings, x_token: str, abha_number: str, scope: list[str], otp_system: str, route: str, description: str
) -> AbdmResult:
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/request/otp"
    payload = {
        "scope": scope,
        "loginHint": "abha-number",
        "loginId": _encrypt_abha_login(settings, abha_number),
        "otpSystem": otp_system,
    }
    return _execute(route, "POST", url, _headers(x_token), payload, description, retry=False)


def request_link_mobile_otp(settings: Settings, x_token: str, abha_number: str) -> AbdmResult:
    """Sends a REAL SMS (whichever channel ABDM has on file for this ABHA number). Never retried."""
    log_phase("Requesting ABHA-Number link OTP via mobile")
    return _request_link_otp(
        settings, x_token, abha_number, MOBILE_LINK_SCOPE, "abdm",
        "/phr/profile/link/mobile/request-otp", "PHR link ABHA number (mobile) OTP request",
    )


def request_link_aadhaar_otp(settings: Settings, x_token: str, abha_number: str) -> AbdmResult:
    """Sends a REAL OTP via UIDAI. Never retried."""
    log_phase("Requesting ABHA-Number link OTP via Aadhaar")
    return _request_link_otp(
        settings, x_token, abha_number, AADHAAR_LINK_SCOPE, "aadhaar",
        "/phr/profile/link/aadhaar/request-otp", "PHR link ABHA number (Aadhaar) OTP request",
    )


def _verify_link_otp(settings: Settings, x_token: str, txn_id: str, otp: str, scope: list[str], route: str, description: str) -> AbdmResult:
    """
    otpValue uses _encrypt_abha_login() (the PROFILE certificate), NOT
    the ordinary _encrypt() -- CORRECTED, same reasoning as the loginId
    fix in _request_link_otp(), applied here BEFORE a live failure forced
    it rather than after: MOBILE_LINK_SCOPE/AADHAAR_LINK_SCOPE both
    contain "abha-login", and abha_address_creation.py's own banner
    already established (P1-H, confirmed by a live before/after test)
    that certificate choice tracks the SCOPE containing "abha-login", not
    which field is being encrypted or which URL the call hits. Untested
    live as of this fix -- report back if this one is also wrong.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/verify"
    payload = {
        "scope": scope,
        "authData": {
            "authMethods": ["otp"],
            "otp": {"txnId": txn_id, "otpValue": _encrypt_abha_login(settings, otp)},
        },
    }
    return _execute(
        route, "POST", url, _headers(x_token), payload, description,
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile", "email"),
    )


def verify_link_mobile_otp(settings: Settings, x_token: str, txn_id: str, otp: str) -> AbdmResult:
    """
    Confirmed live shape (Postman): txnId, message, authResult, users[]
    (lowercase abhaNumber), accounts[] (PascalCase ABHANumber, richer --
    demographics, profilePhoto AND kycPhoto, authMethods[],
    verificationStatus/verificationType, preferredAbhaAddress, empty
    tags: {}), tokens (token/expiresIn: 1800/refreshToken/
    refreshExpiresIn: 1296000). A wrong/expired OTP can be HTTP 200 with
    authResult: "failed" and users: [] -- check authResult, not just
    status_code. Casing quirk NOT normalized -- see module banner.
    """
    log_phase("Verifying ABHA-Number link OTP via mobile")
    return _verify_link_otp(
        settings, x_token, txn_id, otp, MOBILE_LINK_SCOPE,
        "/phr/profile/link/mobile/verify-otp", "PHR link ABHA number (mobile) OTP verify",
    )


def verify_link_aadhaar_otp(settings: Settings, x_token: str, txn_id: str, otp: str) -> AbdmResult:
    """Same confirmed shape as verify_link_mobile_otp() -- see that function's own docstring."""
    log_phase("Verifying ABHA-Number link OTP via Aadhaar")
    return _verify_link_otp(
        settings, x_token, txn_id, otp, AADHAAR_LINK_SCOPE,
        "/phr/profile/link/aadhaar/verify-otp", "PHR link ABHA number (Aadhaar) OTP verify",
    )


def process_link(settings: Settings, x_token: str, transaction_id: str, action: str) -> AbdmResult:
    """
    POST /phr/app/login/profile/link -- {"action": action, "transactionId":
    transaction_id}. `action` is "LINK" (spec-confirmed, SS3.33/3.36) or
    "DELINK" (a HYPOTHESIS, UNVERIFIED -- see module banner's DE-LINK
    section). If this returns something other than the confirmed LINK
    success shape or the known "Invalid Account Action" error, treat it
    as new information to report, not something to guess around.

    Confirmed success shape (LINK): {"message": "ABHA number is securely
    linked to ABHA address", "authResult": "success"}.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/link"
    payload = {"action": action, "transactionId": transaction_id}
    log_phase(f"Processing ABHA-Number {action} request")
    return _execute(
        "/phr/profile/link/process", "POST", url, _headers(x_token), payload, f"PHR ABHA number {action.lower()}"
    )


# ---------------------------------------------------------------------------
# Switch Profile -- SS3.37-3.38
# ---------------------------------------------------------------------------

def request_switch_profile(settings: Settings, x_token: str) -> AbdmResult:
    """
    GET /phr/app/login/profile/switch-profile -- spec's own response body
    is blank; live Postman (343KB capture) shows txnId + users[] (real,
    heterogeneous ABHA profiles for the account) + tokens (expiresIn: 300,
    refreshToken: null -- this project's own "transient token" shape).
    tokens.token from THIS response is the T-token verify_switch_profile()
    needs. Gating rule (spec: ABHA-Address logins can't switch) is
    enforced in testui, not here -- see module banner.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/switch-profile"
    log_phase("Requesting Switch Profile account list")
    return _execute("/phr/profile/switch/request", "GET", url, _headers(x_token), None, "PHR switch profile request")


def verify_switch_profile(settings: Settings, t_token: str, abha_address: str, txn_id: str) -> AbdmResult:
    """
    POST /phr/app/login/profile/verify/switch-profile/user -- T-token
    header, NOT X-Token (see module banner). Response is a BARE top-level
    token/expiresIn/refreshToken -- testui's session.ts has a dedicated
    extractBareSessionToken() for this shape.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/verify/switch-profile/user"
    payload = {"abhaAddress": abha_address, "txnId": txn_id}
    log_phase(f"Switching active profile to {abha_address}")
    return _execute("/phr/profile/switch/verify", "POST", url, _headers_t_token(t_token), payload, "PHR switch profile verify")


# ---------------------------------------------------------------------------
# QR Code / PHR Card -- SS3.40 / SS3.41
# ---------------------------------------------------------------------------

def get_qr_code(settings: Settings, x_token: str) -> BinaryResult:
    """GET /phr/app/login/profile/qrCode -- spec: 202 Accepted. Real payload shape UNCONFIRMED -- see module banner."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/qrCode"
    log_phase("Fetching QR code")
    return _execute_binary("/phr/profile/qr-code", url, _headers(x_token), "PHR get QR code")


def get_phr_card(settings: Settings, x_token: str) -> BinaryResult:
    """GET /phr/app/login/profile/phrCard -- NOT the ABHA card (abha_card.py) -- see module banner."""
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/phrCard"
    log_phase("Fetching PHR card")
    return _execute_binary("/phr/profile/phr-card", url, _headers(x_token), "PHR get PHR card")


# ---------------------------------------------------------------------------
# Generate Refresh Token -- SS3.43
# ---------------------------------------------------------------------------

def refresh_token(settings: Settings, r_token: str) -> AbdmResult:
    """
    GET /phr/app/login/profile/request/token -- R-token header, not
    X-Token (see module banner). Response: {"tokens": {token, expiresIn:
    1800, refreshToken, refreshExpiresIn: 1296000}} -- WRAPPED, unlike
    Switch-Profile-Verify's bare shape; session.ts's EXISTING
    extractSessionToken() is the right reader for this one.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/profile/request/token"
    log_phase("Refreshing session token")
    return _execute("/phr/profile/refresh-token", "GET", url, _headers_r_token(r_token), None, "PHR refresh token")
