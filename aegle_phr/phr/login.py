"""
Login for an ABHA address created via mobile enrollment (P1-A): password
(P1-C), mobile OTP (P1-D), and five more OTP-based identifier/channel
combinations (P1-E) -- ABHA Number via Aadhaar OTP, raw Aadhaar Number via
Aadhaar OTP, ABHA Number via Mobile OTP, ABHA Address via Mobile OTP, and
ABHA Address via Email OTP. Face-verify appears only as diagrams in the
spec section covering these methods, with no API section of its own --
confirmed absent, not a gap in this module.

One function per call, mirroring aegle_phr/phr/enrollment.py's shape (raw
body + status returned, archived to abdm_call_log). The private request
plumbing below (_headers/_parse/_execute/_encrypt) is a deliberate
near-duplicate of enrollment.py's -- see the note at the bottom of this
banner for why it was not factored out in this chunk.

=============================================================================
UNDOCUMENTED RESPONSE SHAPE -- /phr/app/login/verify
=============================================================================
Same gap pattern as P1-A: ABDM's spec gives complete request bodies but only
documents /login/verify's ERROR cases --

    wrong password -> 200 {"message": "Password did not match, please try
                            again", "authResult": "failed", "users": []}
    blank password -> 400, an array of {code, message}

-- and leaves the SUCCESS shape unspecified. Expected, by analogy with
mobile enrollment's own /enrollment/verify, to resemble a `users` list plus
a short-lived token -- but that is a guess, not a fact, and nothing in this
module encodes it. verify_password() returns the raw body untouched; the
first live run is what tells us the real shape (captured into
aegle-phr/README.md's "Captured ABDM response shapes" section once it
runs).

/phr/app/login/search and /phr/app/login/verify/user ARE documented -- see
SearchUserResponse and VerifyUserResponse below. Even those are returned
raw, same as enrollment.py's RequestOtpResponse: the model records the
documented contract, it does not gate the response.
=============================================================================

ENCRYPTION: password is RSA-encrypted against settings.phr_certificate_url,
via the same abdm_core.rsa_crypto helpers enrollment.py uses -- see that
module's own banner for why this must be the PHR certificate endpoint and
not the sibling HIP/HIU repo's /profile/public/certificate.

ENCRYPTION, CORRECTED FOR THREE FLOWS (P1-E's own long-flagged "Invalid
LoginId" mystery, finally root-caused and fixed, confirmed live
2026-09-01): request_abha_number_aadhaar_otp()/request_aadhaar_otp()/
request_abha_number_mobile_otp() and their verify counterparts (SS3.13-18)
do NOT use the PHR certificate above -- their scope starts with
"abha-login", and certificate choice tracks THAT, not the URL path prefix
or which module a call lives in. This is the same rule
abha_address_creation.py's own banner first found (P1-H, a live
before/after test) and aegle_phr/phr/profile_link.py's own Link ABHA
Number independently confirmed again (P1-N) -- see _encrypt_abha_login()
below for the full story. Every OTHER flow in this module (password,
mobile, both ABHA-Address methods) uses "abha-address-login", a
different scope family, unaffected by this and already confirmed
correct on the PHR certificate.

RETRY DECISION -- all three calls here use the DEFAULT call_with_retry
classifier (retry on connection error/timeout/5xx/429/408; never on a normal
200/400 response), unlike enrollment.request_otp()'s single-attempt-only
policy. This needed its own reasoning, not an automatic carry-over from
"don't retry OTP requests":

  - search_user(): a read-only lookup. No side effect to double up on.
    Retrying is straightforwardly safe.

  - verify_password(): NOT an SMS, so the specific cost that ruled out
    retrying request_otp() (a second real message, counted against ABDM's
    lockout) does not apply here. But the STRUCTURAL risk is the same one
    P1-A already accepted for enrollment.verify_otp(): if ABDM processes
    the password check server-side and then the response delivery fails
    transiently (a 5xx after the fact, a dropped connection), a retry would
    silently submit a SECOND password attempt without our code knowing one
    already happened. UNCONFIRMED whether ABDM enforces any failed-attempt
    lockout on this endpoint (nothing in the spec says so, but nothing
    rules it out either). Decided to match P1-A's own precedent for exactly
    this shape of risk (verify_otp was retried, flagged, not blocked) rather
    than invent a stricter rule here that P1-A didn't apply to a structurally
    identical case -- so this stays retryable, flagged the same way.

  - verify_user(): exchanges an already-issued txnId for a token. Closer in
    spirit to abdm_core.session.get_gateway_token() (a stateless credential
    exchange) than to anything that consumes a single-use secret. Retrying
    is safe.

MOBILE OTP LOGIN (P1-D) adds two more calls on top of the three above:

  - request_mobile_otp(): sends a REAL SMS, same cost as
    enrollment.request_otp(). Uses the same single-attempt, never-retry
    policy for the same reason -- retrying risks a second real message
    against ABDM's own rate limits, and a transient HTTP failure does not
    tell us whether the SMS already went out.

  - verify_mobile_otp(): posts to the SAME /phr/app/login/verify endpoint
    verify_password() does, just with a different scope and authData shape
    (authMethods: ["otp"] instead of ["password"]). Uses the DEFAULT retry
    classifier, matching verify_password()'s own precedent exactly -- same
    structural risk (a transient failure after ABDM has already processed
    the OTP server-side), same reasoning, so the same answer.

FIVE MORE OTP LOGIN METHODS (P1-E). Every one of them hits the exact same
two URLs mobile login does (/login/request/otp, /login/verify) and finishes
with the same verify_user() -- they differ only in `scope`, `loginHint`,
`otpSystem`, and what gets encrypted into `loginId`. Rather than copy
request_mobile_otp()/verify_mobile_otp() five more times, the shared shape
was factored out into _request_otp_login()/_verify_otp_login() below, and
request_mobile_otp()/verify_mobile_otp() were rewritten to call them too --
a pure internal refactor, their external signatures and behaviour are
unchanged. DESIGN CALL, not mandated: six near-identical copies of a
20-line function would have made the actual differences (three scopes vs
two for raw Aadhaar; the capital-A "Aadhaar-number" hint) harder to spot at
a glance, not easier -- with them factored out as named constants passed
into two shared functions, every method's own function is just its
constants plus a docstring about what's specific to it.

REDACTION, extended for this batch: `extra_response_secrets` on every OTP
verify call (mobile's included) now defensively checks for "mobile",
"email", "aadhaarNumber" and "healthIdNumber" -- not just "mobile" as
before. P1-C found an undocumented plaintext leak on ONE endpoint
(search's "mobile"); the standing lesson applied here is that this class
of surprise is a property of "endpoint we haven't captured a real response
from yet", not of any one specific endpoint, so every new identifier type
this batch introduces gets the same defensive treatment before its first
live call rather than after. redaction.py itself gained one new rule:
"aadhaar" as a secret key fragment, since a raw or partially-masked Aadhaar
number is exactly the kind of value "mobile" and "password" were already
being protected as.

SCOPE/loginHint/otpSystem SOURCING: four of these five flows have their
request/otp body fully specified in the task (scope, loginHint, loginId,
otpSystem all given explicitly, transcribed from spec sections). The
FIFTH -- ABHA Address via Email OTP -- was given only loginHint ("email")
and what to encrypt (the email); scope and otpSystem were not specified.
Those two values here (ABHA_ADDRESS_EMAIL_LOGIN_SCOPE = ["abha-address-login",
"email-verify"], otp_system="abdm") are inferred by pattern-matching the
other four flows' own naming convention -- "{category}-login" +
"{channel}-verify" for scope, "abdm" for otpSystem when ABDM's own gateway
dispatches the OTP (true for every channel except Aadhaar's, which uses
UIDAI's system and says so explicitly via otpSystem="aadhaar"). This is a
GUESS, clearly flagged, not a documented fact -- the live run for this
flow is what confirms or corrects it, same as every other undocumented
shape in this project.
"""

import time
from dataclasses import dataclass
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

# The scope lists used by each verify call. Each pair below is used
# identically for BOTH request/otp and verify -- confirmed explicitly for
# four of the five P1-E flows; inferred by the same pattern for the fifth
# (email) -- see this module's banner.
PASSWORD_LOGIN_SCOPE = ["abha-address-login", "password-verify"]
MOBILE_LOGIN_SCOPE = ["abha-address-login", "mobile-verify"]

# P1-E additions. Spec section numbers noted so a reviewer can find the
# source without re-deriving which flow is which.
ABHA_NUMBER_AADHAAR_LOGIN_SCOPE = ["abha-login", "aadhaar-verify"]              # SS3.13-14
AADHAAR_NUMBER_LOGIN_SCOPE = ["abha-login", "aadhaar-verify", "aadhaar-otp-verify"]  # SS3.15-16, THREE scopes
ABHA_NUMBER_MOBILE_LOGIN_SCOPE = ["abha-login", "mobile-verify"]                # SS3.17-18
ABHA_ADDRESS_MOBILE_LOGIN_SCOPE = ["abha-address-login", "mobile-verify"]       # SS3.19-20 (identical to mobile login's own scope, by identifier not by accident -- both are keyed by ABHA address / mobile channel)
# UNCONFIRMED -- see banner. Scope/otpSystem inferred, not given in the spec excerpt.
ABHA_ADDRESS_EMAIL_LOGIN_SCOPE = ["abha-address-login", "email-verify"]         # SS3.21-22, INFERRED

_TIMEOUT_SECONDS = 30


class SearchUserResponse(BaseModel):
    """Documented /phr/app/login/search success shape. Not used to gate the response."""

    healthIdNumber: str
    abhaAddress: str
    authMethods: list[str]
    blockedAuthMethods: list[str] = []
    status: str
    message: str | None = None


class VerifyUserResponse(BaseModel):
    """
    Documented /phr/app/login/verify/user success shape -- the real X-token
    grant. Not used to gate the response.
    """

    token: str
    expiresIn: int
    refreshToken: str
    refreshExpiresIn: int


def _headers(t_token: str | None = None) -> dict[str, str]:
    """
    Args:
        t_token: CONFIRMED LIVE, 2026-08-28 -- see verify_user()'s own
            docstring for the full story. /login/verify/user needs the
            short-lived transfer token from /login/verify's own response
            sent as a SEPARATE header named "T-token" -- Authorization
            stays the ordinary gateway token, unchanged, for every call in
            this module including this one. None (every call site except
            verify_user()'s own use) omits the header entirely.
    """
    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
    }
    if t_token is not None:
        headers["T-token"] = f"Bearer {t_token}"
    return headers


def _parse(response: requests.Response) -> Any:
    """Parsed JSON when possible, raw text otherwise. Mirrors enrollment.py's _parse()."""
    try:
        return response.json()
    except ValueError:
        return response.text


def _never_transient(response: Any, exception: Any) -> bool:
    """
    Classifier for request_mobile_otp(): NOTHING is retryable. Mirrors
    enrollment.py's own _never_transient() and exists for the identical
    reason -- see this module's banner (MOBILE OTP LOGIN section) and
    enrollment.request_otp()'s own docstring for the full reasoning: a
    failed response does not tell us whether the SMS already went out, so
    even a 5xx is not safe to repeat.
    """
    return False


def _execute(
    route: str,
    url: str,
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
    extra_response_secrets: Callable[[Any], tuple[str, ...]] | None = None,
    retry: bool = True,
    t_token: str | None = None,
) -> AbdmResult:
    """
    Performs one ABDM call, archives it, and returns the raw result.

    Never calls raise_for_status(): a 400 from ABDM ("wrong password",
    "user not found") is an expected, handled outcome, not an exception.
    All three calls in this module use the default (transient-only) retry
    classifier -- see this module's own banner for why, per call.

    Args:
        extra_response_secrets: REDACTION GAP FIX, added after the
            2026-08-27 live run. Two of this module's three endpoints have
            an undocumented response shape (search's extra fields turned
            out to be undocumented too, in practice -- see search_user()'s
            own docstring). redaction.py's key-based rule assumes a key
            name like "mobile" carries the same meaning everywhere it
            appears; that assumption is written for the ENROLLMENT flow's
            REQUEST bodies, where "mobile" always holds RSA ciphertext, and
            it is exempted there via _CIPHERTEXT_SAFE_PATHS. It broke the
            first time an ABDM RESPONSE reused the same key name for a
            genuine plaintext value. This callback lets a caller inspect
            the PARSED response body -- something _execute() only has
            after the call returns, so it cannot be supplied up front the
            way plaintext_secrets is -- and name any additional plaintext
            values found in it. Those are merged into plaintext_secrets
            before archiving, so the value-based scrub (which runs
            regardless of any key's ciphertext-safe exemption) still
            catches them. redaction.py itself is left exactly as it is:
            its assumption is correct for the flow it was written for.
        retry: False for request_mobile_otp() ONLY -- see _never_transient()
            above and enrollment.request_otp()'s own docstring. True
            (default) everywhere else in this module.
        t_token: Forwarded to _headers() -- see its own docstring. None
            everywhere except verify_user()'s required T-token header.
    """
    headers = _headers(t_token)
    started = time.monotonic()

    def attempt() -> requests.Response:
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


def _plaintext_string_fields(body: Any, *field_names: str) -> tuple[str, ...]:
    """
    Pulls named string fields out of a dict response body, if present and
    non-empty. Used as an extra_response_secrets callback -- see
    _execute()'s docstring for why this exists.
    """
    if not isinstance(body, dict):
        return ()
    found = []
    for name in field_names:
        value = body.get(name)
        if isinstance(value, str) and value != "":
            found.append(value)
    return tuple(found)


def _encrypt(settings: Settings, value: str) -> str:
    """RSA-OAEP against the PHR certificate. Never log the input. NOT used for the three "abha-login"-scoped flows below (SS3.13-18) -- see _encrypt_abha_login()."""
    public_key = get_public_certificate(settings.phr_certificate_url)
    return encrypt_value(value, public_key)


def _encrypt_abha_login(settings: Settings, value: str) -> str:
    """
    CORRECTED (confirmed live 2026-09-01): a THIRD, independent
    confirmation of a rule this project has now hit three times --
    certificate choice tracks whether the call's `scope` contains
    "abha-login", not the URL path prefix, and not which module the call
    happens to live in. First found in aegle_phr/phr/abha_address_creation.py
    (P1-H, a live before/after test on that endpoint). Confirmed again in
    aegle_phr/phr/profile_link.py (P1-N, Link ABHA Number's request/otp
    AND verify, both live-fixed the same way). This module's own
    request_abha_number_aadhaar_otp()/request_aadhaar_otp()/
    request_abha_number_mobile_otp() (SS3.13-18) were BOTH flagged,
    independently, by both of those chunks' own banners as almost
    certainly having the identical bug, and never actually fixed here
    until now -- this closes that loop.

    Used by _request_otp_login()/_verify_otp_login() ONLY when
    use_abha_login_scope=True is passed at the call site -- i.e. only for
    the three flows below whose scope literally starts with "abha-login"
    (ABHA_NUMBER_AADHAAR_LOGIN_SCOPE, AADHAAR_NUMBER_LOGIN_SCOPE,
    ABHA_NUMBER_MOBILE_LOGIN_SCOPE). Every OTHER flow in this module
    (password login, mobile login, both ABHA-Address login methods) uses
    "abha-address-login", a DIFFERENT scope family, already confirmed
    live to work correctly on the ordinary _encrypt() (PHR certificate) --
    those are UNCHANGED by this fix, on purpose. Don't widen this beyond
    the three flows that actually match the rule.
    """
    public_key = get_public_certificate(settings.abdm_profile_certificate_url)
    return encrypt_value(value, public_key)


# Defensive field names checked on EVERY OTP-based login verify response,
# regardless of which identifier that flow uses. Extended in P1-E (was just
# "mobile") on the standing lesson from P1-C/P1-D: an undocumented plaintext
# leak is a property of "an endpoint whose real response we haven't
# captured yet", not of any one specific endpoint. A no-op for whichever of
# these fields never actually appears in a given flow's response.
_OTP_VERIFY_DEFENSIVE_FIELDS = ("mobile", "email", "aadhaarNumber", "healthIdNumber")


def _request_otp_login(
    settings: Settings,
    route: str,
    description: str,
    scope: list[str],
    login_hint: str,
    login_id_plaintext: str,
    otp_system: str,
    use_abha_login_scope: bool = False,
) -> AbdmResult:
    """
    Shared plumbing for every OTP-based login method's request/otp call
    (mobile login's included, since P1-E). NEVER RETRIED -- every caller
    sends a real OTP (SMS, email, or via UIDAI for Aadhaar), and a
    transient HTTP failure does not tell us whether it already went out --
    see enrollment.request_otp()'s own docstring for the original version
    of this reasoning.

    use_abha_login_scope: CORRECTED (P1-N-adjacent fix, confirmed live):
    True for the three "abha-login"-scoped flows (SS3.13-18), which need
    _encrypt_abha_login() (the PROFILE certificate) for loginId instead of
    the ordinary _encrypt() every other flow here correctly uses -- see
    _encrypt_abha_login()'s own docstring for the full story.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/request/otp"
    encrypt = _encrypt_abha_login if use_abha_login_scope else _encrypt

    payload = {
        "scope": scope,
        "loginHint": login_hint,
        "loginId": encrypt(settings, login_id_plaintext),
        "otpSystem": otp_system,
    }

    return _execute(
        route=route,
        url=url,
        payload=payload,
        description=description,
        plaintext_secrets=(login_id_plaintext,),
        retry=False,
    )


def _verify_otp_login(
    settings: Settings,
    route: str,
    description: str,
    scope: list[str],
    txn_id: str,
    otp: str,
    use_abha_login_scope: bool = False,
) -> AbdmResult:
    """
    Shared plumbing for every OTP-based login method's verify call (mobile
    login's included, since P1-E). Uses the DEFAULT retry classifier --
    see verify_mobile_otp()'s own docstring (now folded into this function)
    for why that matches verify_password()'s precedent.

    use_abha_login_scope: see _request_otp_login()'s own docstring -- the
    SAME three flows need this for otpValue too, not just loginId.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/verify"
    encrypt = _encrypt_abha_login if use_abha_login_scope else _encrypt

    payload = {
        "scope": scope,
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "txnId": txn_id,
                "otpValue": encrypt(settings, otp),
            },
        },
    }

    return _execute(
        route=route,
        url=url,
        payload=payload,
        description=description,
        plaintext_secrets=(otp,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, *_OTP_VERIFY_DEFENSIVE_FIELDS),
    )


# ---------------------------------------------------------------------------
# 1. Search user  --  POST /phr/app/login/search
# ---------------------------------------------------------------------------

def search_user(settings: Settings, abha_address: str) -> AbdmResult:
    """
    Documented response: 200 with {healthIdNumber, abhaAddress, authMethods,
    blockedAuthMethods, status, message}. Documented error: unknown address
    -> 400 {"code": "ABDM-1211", "message": "User not found."}.

    Callers must check `authMethods` for "PASSWORD" before offering the
    password field -- it is not guaranteed to be present for every address.

    UNDOCUMENTED IN PRACTICE (found on the 2026-08-27 live run, not in the
    spec): the sandbox's real response carries at least two fields beyond
    the documented six -- "fullName" and "mobile", both in plaintext.
    "fullName" is already covered by redaction.py's key-based rule.
    "mobile" is not (see _execute()'s extra_response_secrets docstring for
    why), so it is named explicitly below.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/search"

    payload = {"abhaAddress": abha_address}

    log_phase(f"Searching ABHA address for login: {abha_address}")
    return _execute(
        route="/phr/login/search",
        url=url,
        payload=payload,
        description="PHR login user search",
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile"),
    )


# ---------------------------------------------------------------------------
# 2. Verify password  --  POST /phr/app/login/verify
# ---------------------------------------------------------------------------

def verify_password(settings: Settings, abha_address: str, password: str) -> AbdmResult:
    """
    SUCCESS RESPONSE SHAPE UNDOCUMENTED -- see this module's banner. Only
    the two error shapes are specified; both are ordinary HTTP responses
    (200 with authResult: "failed", or 400) that _execute()'s default retry
    classifier never touches, so a wrong password is returned to the caller
    on the first attempt regardless of the retry policy below.

    Since the success shape is unknown, `mobile` is named defensively as an
    extra_response_secrets field -- search_user() just demonstrated that
    ABDM will put a plaintext mobile number under exactly that key in a
    login-flow response with no warning. Cheap insurance against the same
    thing happening here; a no-op if the field never appears.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/verify"

    payload = {
        "scope": PASSWORD_LOGIN_SCOPE,
        "authData": {
            "authMethods": ["password"],
            "password": {
                "abhaAddress": abha_address,
                "password": _encrypt(settings, password),
            },
        },
    }

    log_phase(f"Verifying password login for {abha_address}")
    return _execute(
        route="/phr/login/verify",
        url=url,
        payload=payload,
        description="PHR password login verify",
        plaintext_secrets=(password,),
        extra_response_secrets=lambda body: _plaintext_string_fields(body, "mobile"),
    )


# ---------------------------------------------------------------------------
# 3. Verify user (issue the session token)  --  POST /phr/app/login/verify/user
# ---------------------------------------------------------------------------

def verify_user(settings: Settings, abha_address: str, txn_id: str, t_token: str) -> AbdmResult:
    """
    Documented response: 200 with {token, expiresIn, refreshToken,
    refreshExpiresIn} -- the real X-token grant.

    ABDM describes this endpoint generically ("verify the user from the
    list of ABHA addresses received in the response of verify OTP/face
    authentication API"), not as password-specific -- built standalone,
    taking only abhaAddress/txnId/t_token, so every other login method can
    call it unchanged once built.

    T_TOKEN IS REQUIRED -- CONFIRMED LIVE, 2026-08-28, NOT IN THE SPEC
    EXCERPT AVAILABLE HERE. This endpoint's Authorization header alone
    (the same gateway session token every other call in this module sends)
    is NOT sufficient: it returns a bare 401 with an empty body, regardless
    of which valid, real, currently-linked ABHA address is supplied --
    tested against two, one KYC-PENDING and one KYC-VERIFIED, ruling out
    the address as the variable. Sending the /login/verify response's own
    short-lived (5-minute) transfer token (`tokens.token`, "typ":
    "Transfer") AS the Authorization header instead was also tried and is
    ALSO wrong -- that returned a real error body, {"code": "900901",
    "message": "Invalid Credentials", ...}, an ABDM GATEWAY-level
    authentication rejection.

    The actual answer, confirmed working with a live token/txnId pair
    minutes later: Authorization stays the ordinary gateway token, and the
    transfer token goes in a SEPARATE header, "T-token" (value prefixed
    "Bearer ", same as Authorization). With both present, this endpoint
    returns 200 with the full documented shape.

    t_token comes from the SAME /login/verify (or eventually /login/face)
    response that produced txn_id -- callers must carry both forward
    together, not just txn_id alone.
    """
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/phr/app/login/verify/user"

    payload = {"abhaAddress": abha_address, "txnId": txn_id}

    log_phase(f"Exchanging login txnId for a session token: {abha_address}")
    return _execute(
        route="/phr/login/verify-user",
        url=url,
        payload=payload,
        description="PHR login verify user",
        t_token=t_token,
    )


# ---------------------------------------------------------------------------
# 4. Request mobile OTP (login)  --  POST /phr/app/login/request/otp
# ---------------------------------------------------------------------------

def request_mobile_otp(settings: Settings, mobile: str) -> AbdmResult:
    """
    Sends a REAL SMS. Never retried -- see _request_otp_login()'s own
    docstring.

    Documented response: 200 with {"txnId": "...", "message": "..."}, same
    shape as enrollment.request_otp()'s.

    Delegates to the shared _request_otp_login() (added in P1-E) with this
    method's own scope/hint/otpSystem -- a pure internal refactor, this
    function's own signature and behaviour are unchanged.
    """
    log_phase("Requesting mobile OTP login (real SMS)")
    return _request_otp_login(
        settings,
        route="/phr/login/request-otp",
        description="PHR mobile login OTP request",
        scope=MOBILE_LOGIN_SCOPE,
        login_hint="mobile-number",
        login_id_plaintext=mobile,
        otp_system="abdm",
    )


# ---------------------------------------------------------------------------
# 5. Verify mobile OTP (login)  --  POST /phr/app/login/verify
# ---------------------------------------------------------------------------

def verify_mobile_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    SUCCESS RESPONSE SHAPE UNDOCUMENTED -- same gap as verify_password().
    The spec's only documented shape for this endpoint (with authMethods:
    ["otp"]) is the WRONG-OTP error: 200 with {txnId, message: "Entered OTP
    is incorrect...", authResult: "failed", users: []}. By the presence of
    `users` and `txnId` even in that failure shape, the success response is
    expected to carry a populated `users` list (every ABHA address linked
    to this mobile -- confirmed by the spec's own prose) and a usable
    txnId to chain into verify_user(). That is an expectation, not a fact:
    nothing here encodes it, and the real success shape is only known once
    a live run captures it (see aegle-phr/README.md's captured-shapes
    section). password login's own verify already showed once that a
    "should have a txnId by analogy" guess can be wrong.

    Delegates to the shared _verify_otp_login() (added in P1-E), which now
    checks the broader _OTP_VERIFY_DEFENSIVE_FIELDS set rather than just
    "mobile" -- a strengthening, not a behaviour change for this call
    specifically (mobile login's own response never had the other fields).
    """
    log_phase("Verifying mobile OTP login")
    return _verify_otp_login(
        settings,
        route="/phr/login/verify-otp",
        description="PHR mobile login OTP verify",
        scope=MOBILE_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
    )


# ---------------------------------------------------------------------------
# 6/7. ABHA Number login, via Aadhaar OTP  --  spec SS3.13-14
# ---------------------------------------------------------------------------
# OTP goes to the AADHAAR-REGISTERED mobile, not whatever mobile (if any) is
# on the ABHA profile -- the two can differ, and this flow deliberately uses
# whichever one UIDAI has on file for that Aadhaar.

def request_abha_number_aadhaar_otp(settings: Settings, abha_number: str) -> AbdmResult:
    """Sends a REAL OTP to the Aadhaar-registered mobile. Never retried. CORRECTED (confirmed live): uses the PROFILE certificate for loginId -- see _encrypt_abha_login()'s own docstring."""
    log_phase("Requesting ABHA Number login OTP via Aadhaar (real OTP)")
    return _request_otp_login(
        settings,
        route="/phr/login/abha-number-via-aadhaar/request-otp",
        description="PHR ABHA Number login (Aadhaar OTP) request",
        scope=ABHA_NUMBER_AADHAAR_LOGIN_SCOPE,
        login_hint="abha-number",
        login_id_plaintext=abha_number,
        otp_system="aadhaar",
        use_abha_login_scope=True,
    )


def verify_abha_number_aadhaar_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """SUCCESS RESPONSE SHAPE UNDOCUMENTED -- same gap as every other verify in this module. CORRECTED (untested live as of this fix): otpValue also uses the PROFILE certificate -- see _encrypt_abha_login()."""
    log_phase("Verifying ABHA Number login OTP via Aadhaar")
    return _verify_otp_login(
        settings,
        route="/phr/login/abha-number-via-aadhaar/verify-otp",
        description="PHR ABHA Number login (Aadhaar OTP) verify",
        scope=ABHA_NUMBER_AADHAAR_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
        use_abha_login_scope=True,
    )


# ---------------------------------------------------------------------------
# 8/9. Raw Aadhaar Number login, via Aadhaar OTP  --  spec SS3.15-16
# ---------------------------------------------------------------------------
# THREE scopes, not two -- the only flow in this module with that shape.
#
# loginHint CORRECTED (confirmed live 2026-09-01, Aayush directly): this
# used to be "Aadhaar-number" with a capital A, copied exactly from the
# spec's own example -- ABDM rejected it live with HTTP 400 {"code":
# "ABDM-9999: ", "message": "Invalid Login Hint"}, a genuinely different
# error shape from the certificate-mismatch one every other flow in this
# batch hit (this one names the FIELD, "Login Hint", not "LoginId"). The
# correct value is bare "aadhaar" -- matching aegle_phr/phr/
# aadhaar_enrollment.py's own request_aadhaar_enrollment_otp(), a
# DIFFERENT (enrollment, not login) flow that also identifies someone by
# Aadhaar number and has been confirmed live since P1-F. Not
# "aadhaar-number" (an earlier, untested guess this comment briefly
# carried before Aayush corrected it directly) -- same lesson as ABDM's
# scope/hint strings being case- and value-sensitive every time this
# project has tested one, and worth checking an already-confirmed sibling
# flow before guessing at a plausible-looking variant.
#
# This is the one flow in the batch with a real documented verify SUCCESS
# body (every other verify in this project has had its success shape
# blank in the spec). Treated as a starting reference, not gospel -- every
# other "documented" response this project has captured has had at least
# one live surprise. Two things the documented example itself is worth
# recording, not silently trusting:
#   1. `preferredAbhaAddress` -- not seen in any other verify response
#      captured so far. If genuinely present live, the UI pre-selects it
#      visually in the picker; nothing beyond that is built around it,
#      since nothing documents what picking a DIFFERENT address does
#      differently.
#   2. The spec's own placeholder for the transfer token is literally
#      "{{encrypted-T-token}}" -- the spec DOES name this field "T-token",
#      just in a completely different section from /login/verify/user,
#      where the previous chunk had to discover the same name live,
#      undocumented. Worth remembering next time a header name is missing
#      from the section that actually needs it: check whether another
#      section already named it.

def request_aadhaar_otp(settings: Settings, aadhaar_number: str) -> AbdmResult:
    """
    Sends a REAL OTP via UIDAI. Never retried. CORRECTED, confirmed live
    in two separate rounds: (1) uses the PROFILE certificate for loginId
    -- see _encrypt_abha_login()'s own docstring; (2) loginHint is bare
    "aadhaar", not the spec's own capitalized "Aadhaar-number" -- see this
    section's own banner comment.
    """
    log_phase("Requesting raw Aadhaar Number login OTP (real OTP)")
    return _request_otp_login(
        settings,
        route="/phr/login/aadhaar-number/request-otp",
        description="PHR Aadhaar Number login request",
        scope=AADHAAR_NUMBER_LOGIN_SCOPE,
        login_hint="aadhaar",
        login_id_plaintext=aadhaar_number,
        otp_system="aadhaar",
        use_abha_login_scope=True,
    )


def verify_aadhaar_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """
    The spec documents a success shape here (see this section's own banner
    comment above) -- but it is treated as a starting reference, checked
    against the real live response, not assumed correct. Returned raw
    either way. CORRECTED (untested live as of this fix): otpValue also
    uses the PROFILE certificate -- see _encrypt_abha_login().
    """
    log_phase("Verifying raw Aadhaar Number login OTP")
    return _verify_otp_login(
        settings,
        route="/phr/login/aadhaar-number/verify-otp",
        description="PHR Aadhaar Number login verify",
        scope=AADHAAR_NUMBER_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
        use_abha_login_scope=True,
    )


# ---------------------------------------------------------------------------
# 10/11. ABHA Number login, via Mobile OTP  --  spec SS3.17-18
# ---------------------------------------------------------------------------
# OTP goes to whatever mobile IS linked to this ABHA number (unlike the
# Aadhaar-OTP variant above, which always uses the Aadhaar-registered one).
#
# Spec business-rule note, recorded but not implemented against: "For users
# logging in with a KYC verified ABHA address, only KYC verified addresses
# should be displayed; for a mix, both KYC verified and pending should be
# displayed." This describes ABDM's OWN server-side filtering of `users[]`
# -- there is nothing for this client to do about it. Noted here so a
# `users[]` list that looks differently filtered across flows is not
# mistaken for a bug in this module.

def request_abha_number_mobile_otp(settings: Settings, abha_number: str) -> AbdmResult:
    """Sends a REAL SMS. Never retried. CORRECTED (confirmed live): uses the PROFILE certificate for loginId -- see _encrypt_abha_login()'s own docstring."""
    log_phase("Requesting ABHA Number login OTP via mobile (real SMS)")
    return _request_otp_login(
        settings,
        route="/phr/login/abha-number-via-mobile/request-otp",
        description="PHR ABHA Number login (mobile OTP) request",
        scope=ABHA_NUMBER_MOBILE_LOGIN_SCOPE,
        login_hint="abha-number",
        login_id_plaintext=abha_number,
        otp_system="abdm",
        use_abha_login_scope=True,
    )


def verify_abha_number_mobile_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """SUCCESS RESPONSE SHAPE UNDOCUMENTED -- same gap as every other verify in this module. CORRECTED (untested live as of this fix): otpValue also uses the PROFILE certificate -- see _encrypt_abha_login()."""
    log_phase("Verifying ABHA Number login OTP via mobile")
    return _verify_otp_login(
        settings,
        route="/phr/login/abha-number-via-mobile/verify-otp",
        description="PHR ABHA Number login (mobile OTP) verify",
        scope=ABHA_NUMBER_MOBILE_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
        use_abha_login_scope=True,
    )


# ---------------------------------------------------------------------------
# 12/13. ABHA Address login, via Mobile OTP  --  spec SS3.19-20
# ---------------------------------------------------------------------------
# Spec note: "When logging in with an ABHA address, the Switch Profile
# option should not be displayed" -- expect tokens.switchProfileEnabled:
# false here. Not hardcoded or acted on client-side; recorded so the value
# isn't mistaken for a bug if it does show up false.

def request_abha_address_mobile_otp(settings: Settings, abha_address: str) -> AbdmResult:
    """Sends a REAL SMS. Never retried."""
    log_phase("Requesting ABHA Address login OTP via mobile (real SMS)")
    return _request_otp_login(
        settings,
        route="/phr/login/abha-address-via-mobile/request-otp",
        description="PHR ABHA Address login (mobile OTP) request",
        scope=ABHA_ADDRESS_MOBILE_LOGIN_SCOPE,
        login_hint="abha-address",
        login_id_plaintext=abha_address,
        otp_system="abdm",
    )


def verify_abha_address_mobile_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """SUCCESS RESPONSE SHAPE UNDOCUMENTED -- same gap as every other verify in this module."""
    log_phase("Verifying ABHA Address login OTP via mobile")
    return _verify_otp_login(
        settings,
        route="/phr/login/abha-address-via-mobile/verify-otp",
        description="PHR ABHA Address login (mobile OTP) verify",
        scope=ABHA_ADDRESS_MOBILE_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
    )


# ---------------------------------------------------------------------------
# 14/15. ABHA Address login, via Email OTP  --  spec SS3.21-22 (marked "Optional")
# ---------------------------------------------------------------------------
# "Optional" in the spec, built anyway: the section's own note says "This
# login functionality is available for the integrator, not for the ABHA
# app" -- Aegle IS the integrator here (a third-party PHR app, not the
# official ABHA app), so this applies to us.
#
# SPEC SELF-CONTRADICTION, flagged rather than resolved: the section's
# prose says "the login hint should be the ABHA address," but its own
# request-body EXAMPLE shows loginHint="email" with loginId being the
# encrypted EMAIL address, not the ABHA address -- contradicting its own
# description one sentence earlier. Built against the example body (more
# concrete than prose, and this project's own precedent -- P1-C's verify
# shape, the T-token gap -- has consistently favoured the live sandbox and
# concrete examples over prose when the two disagree). The live run is
# what actually settles which one ABDM accepts; see this function's own
# call site in the README's captured-shapes section for the resolution.
#
# SCOPE AND otpSystem ARE INFERRED, not given in the spec excerpt available
# for this task -- see this module's own banner for the reasoning
# (pattern-matched against the other four flows' naming convention).
# UNCONFIRMED until the live run either bears this out or corrects it.

def request_abha_address_email_otp(settings: Settings, email: str) -> AbdmResult:
    """
    Sends a REAL email OTP. Never retried -- same reasoning as every other
    OTP request in this module, even though the channel differs.

    loginId is the ENCRYPTED EMAIL ADDRESS, per the spec's own example body
    -- not the ABHA address, despite the section's prose saying otherwise.
    See this function's section banner above.
    """
    log_phase("Requesting ABHA Address login OTP via email (real email)")
    return _request_otp_login(
        settings,
        route="/phr/login/abha-address-via-email/request-otp",
        description="PHR ABHA Address login (email OTP) request",
        scope=ABHA_ADDRESS_EMAIL_LOGIN_SCOPE,
        login_hint="email",
        login_id_plaintext=email,
        otp_system="abdm",
    )


def verify_abha_address_email_otp(settings: Settings, txn_id: str, otp: str) -> AbdmResult:
    """SUCCESS RESPONSE SHAPE UNDOCUMENTED -- same gap as every other verify in this module."""
    log_phase("Verifying ABHA Address login OTP via email")
    return _verify_otp_login(
        settings,
        route="/phr/login/abha-address-via-email/verify-otp",
        description="PHR ABHA Address login (email OTP) verify",
        scope=ABHA_ADDRESS_EMAIL_LOGIN_SCOPE,
        txn_id=txn_id,
        otp=otp,
    )
