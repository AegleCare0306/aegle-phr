"""
The locker's OWN outbound HIU calls: section 6 consent (init, fetch) and
section 7 data flow (health-information request).

WHY THIS MODULE EXISTS (P20). These three calls used to be made by
importing repo/server/hiu_consent.py and repo/server/hiu_health_information.py
at runtime. That made a PHR app structurally unable to run unless a HIP/HIU
backend happened to be in the same process -- backwards for an app whose
whole premise is that a patient's locker is its own ABDM entity. Nothing
here imports repo/. Every primitive comes from abdm_core (retry, request
ids, gateway token, Fidelius key material), exactly as the rest of
aegle_phr already does.

NOT A COPY OF repo/'s VERSION. The payloads and headers are the same
because ABDM's API is the same -- those shapes are confirmed, live-proven,
and there is nothing to improve about them. What differs is everything
around them: correlation goes to locker_pending_request (this app's own
table), the local pre-flight checks read this app's own consent artefacts,
and every call is archived through aegle_phr's own call_log/redaction, so a
secret never reaches a log. repo/'s copies are untouched and still serve
repo/'s own HIU role.

ASYNC BY NATURE. All three calls are acknowledged 202 with an ack-only
body: none of them returns the thing you actually asked for. The
consentRequest.id, the artefact and the transactionId each arrive later on
a separate inbound callback (aegle_phr/callbacks/hiu_services.py), matched
back by the REQUEST-ID this module records BEFORE each call goes out.
"""

import time
from typing import Any

import json

import requests

from abdm_core.fidelius import generate_key_material
from abdm_core.http import (
    call_with_retry,
    generate_expiry_time,
    generate_request_id,
    generate_timestamp,
)
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.phr import hip_trust
from aegle_phr.phr import locker_hiu_repository as hiu_repo
from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.phr.redaction import redact
from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30

# How much of a response body goes to the PLAIN-TEXT log. Mirrors
# subscription.py's own constant and reasoning: the full body is always in
# Postgres abdm_call_log, but a status code alone has blocked diagnosis
# before, and Cowork cannot reach Postgres.
_LOG_BODY_MAX_CHARS = 1200

# How long the ephemeral ECDH public key offered on a §7 request stays
# valid. 60 minutes, matching repo/'s own proven-live value -- a transfer
# that has not started within the hour is not going to.
_KEY_EXPIRY_MINUTES = 60


class ConsentNotUsableError(ValueError):
    """
    Raised BEFORE any ABDM call when our own artefact says the request
    cannot succeed -- no artefact held, not GRANTED, or the requested
    range falls outside the approved window.

    Checked locally on purpose. ABDM rejects an out-of-range request
    asynchronously, as ABDM-1063 on the on-request callback, minutes
    later -- slow and avoidable for something we can already rule out.
    """


def _requester_headers(x_cm_id: str, request_id: str, hiu_id: str | None = None) -> dict[str, str]:
    """
    Headers for the locker's HIU-role calls.

    X-HIU-ID IS PER-ENDPOINT, NOT UNIFORM -- confirmed against the real
    Postman collection, and the difference is not cosmetic:
      - consent/v3/request/init sends NO X-HIU-ID; the identity travels in
        the body's consent.hiu.id instead.
      - consent/v3/fetch and data-flow/v3/health-information/request BOTH
        send it as a header.
    Passing hiu_id=None reproduces the first case exactly.

    No X-AUTH-TOKEN on any of them: these are the locker acting as an HIU
    about a patient, not the patient's own session (§7.3.1-7.3.5 take no
    patient token at all).

    request_id is caller-supplied rather than generated here because the
    pending row keyed on it must be written BEFORE the call goes out --
    callbacks have been seen to arrive before our own HTTP response does.
    """
    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-CM-ID": x_cm_id,
    }
    if hiu_id:
        headers["X-HIU-ID"] = hiu_id
    return headers


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _log_response_body(description: str, body: Any) -> None:
    """Truncated, secret-redacted body into the plain-text log."""
    try:
        safe = redact(body, ())
        text = safe if isinstance(safe, str) else json.dumps(safe, default=str)
    except Exception as exc:  # never let logging break a real call
        log_error(f"{description}: could not render response body for logging ({exc})")
        return

    if len(text) > _LOG_BODY_MAX_CHARS:
        text = f"{text[:_LOG_BODY_MAX_CHARS]}... [truncated, full body in abdm_call_log]"
    log_phase(f"{description} response body: {text}")


def _execute(
    route: str,
    url: str,
    headers: dict[str, str],
    payload: Any,
    description: str,
) -> AbdmResult:
    """
    Shared plumbing for the three calls -- mirrors subscription.py's own
    _execute(). Never calls raise_for_status(): a 4xx from ABDM is an
    expected, handled outcome here, not an exception.

    The payload is archived whole. keyMaterial's public key and nonce are
    public by construction (they are what we hand ABDM); the PRIVATE key
    never enters a payload at all -- it goes straight to the pending row
    and nowhere else.
    """
    started = time.monotonic()

    def attempt() -> requests.Response:
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    try:
        response = call_with_retry(attempt, description=description)
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, payload, None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call(description, url, response.status_code)
    _log_response_body(description, body)
    archive(route, url, payload, response.status_code, body, duration_ms, None, ())

    return AbdmResult(status_code=response.status_code, body=body)


# =============================================================================
# 6.x -- Consent request init  --  POST /consent/v3/request/init
# =============================================================================

def initiate_consent_request(
    settings: Settings,
    *,
    hiu_id: str,
    patient_abha_address: str,
    requester_name: str,
    requester_identifier_type: str,
    requester_identifier_value: str,
    requester_identifier_system: str,
    purpose_text: str,
    purpose_code: str,
    purpose_ref_uri: str,
    hi_types: list[str],
    date_range_from: str,
    date_range_to: str,
    data_erase_at: str,
    hip_id: str | None = None,
    care_contexts: list[dict[str, str]] | None = None,
    alert_event_id: str | None = None,
) -> AbdmResult:
    """
    Raises a consent request as the locker.

    hip/careContexts default to literal JSON null, which is the shape a
    general "any hospital" request has always sent. The locker's LINK-alert
    path passes both: an 8.3.11 alert names the exact HIP and care contexts
    that just became available, and a consent raised in response should
    cover those, not everything the patient has anywhere.

    alert_event_id is carried on the pending row, not in the payload --
    it is our own correlation, invisible to ABDM. It is what lets the
    on-init callback advance the right locker_alert without the event id
    having to survive a round trip through ABDM.

    Returns 202 on acceptance. The consentRequest.id is NOT in the
    response; it arrives on the on-init callback.
    """
    request_id = generate_request_id()

    # Written BEFORE the call -- a callback that beats our own HTTP
    # response back still finds its session.
    hiu_repo.create_pending(
        request_id,
        hiu_repo.KIND_CONSENT_INIT,
        patient_id=patient_abha_address,
        hiu_id=hiu_id,
        hip_id=hip_id,
        alert_event_id=alert_event_id,
        detail={
            "hiTypes": hi_types,
            "dateRange": {"from": date_range_from, "to": date_range_to},
            "purposeCode": purpose_code,
        },
    )

    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request/init"

    payload = {
        "consent": {
            "purpose": {
                "text": purpose_text,
                "code": purpose_code,
                "refUri": purpose_ref_uri,
            },
            "patient": {"id": patient_abha_address},
            "hiu": {"id": hiu_id},
            "hip": {"id": hip_id} if hip_id else None,
            "careContexts": care_contexts if care_contexts else None,
            "requester": {
                "name": requester_name,
                "identifier": {
                    "type": requester_identifier_type,
                    "value": requester_identifier_value,
                    "system": requester_identifier_system,
                },
            },
            "hiTypes": hi_types,
            "permission": {
                "accessMode": "VIEW",
                "dateRange": {"from": date_range_from, "to": date_range_to},
                "dataEraseAt": data_erase_at,
                "frequency": {"unit": "HOUR", "value": 0, "repeats": 0},
            },
        }
    }

    # No X-HIU-ID on this one -- see _requester_headers().
    headers = _requester_headers(settings.abdm_x_cm_id, request_id=request_id)

    result = _execute(
        "consent-request-init", url, headers, payload, "Consent init request"
    )

    if not result.ok:
        hiu_repo.update_pending(
            request_id,
            state=hiu_repo.FAILED,
            failure_reason=result.error or f"consent init returned {result.status_code}",
        )

    # The caller needs our REQUEST-ID to correlate, and AbdmResult has no
    # field for it -- returned alongside rather than bolted onto the
    # dataclass, so the dataclass keeps meaning exactly "what ABDM said".
    return AbdmResult(
        status_code=result.status_code,
        body={"requestId": request_id, "response": result.body},
        error=result.error,
    )


# =============================================================================
# 6.x -- Consent fetch  --  POST /consent/v3/fetch
# =============================================================================

def fetch_consent(
    settings: Settings,
    *,
    hiu_id: str,
    consent_id: str,
    patient_id: str | None = None,
    alert_event_id: str | None = None,
) -> AbdmResult:
    """
    Asks ABDM for the full artefact behind a GRANTED consent id.

    202 is ack-only; the artefact arrives on the on-fetch callback and
    lands in locker_consent_artefact. Until it does, the locker holds a
    consent id it cannot legally make a data request with -- which is why
    this call is not optional on the LINK path.
    """
    request_id = generate_request_id()

    hiu_repo.create_pending(
        request_id,
        hiu_repo.KIND_CONSENT_FETCH,
        patient_id=patient_id,
        hiu_id=hiu_id,
        consent_id=consent_id,
        alert_event_id=alert_event_id,
    )

    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/fetch"
    payload = {"consentId": consent_id}
    headers = _requester_headers(settings.abdm_x_cm_id, request_id=request_id, hiu_id=hiu_id)

    result = _execute("consent-fetch", url, headers, payload, "Consent fetch")

    if not result.ok:
        hiu_repo.update_pending(
            request_id,
            state=hiu_repo.FAILED,
            failure_reason=result.error or f"consent fetch returned {result.status_code}",
        )

    return AbdmResult(
        status_code=result.status_code,
        body={"requestId": request_id, "response": result.body},
        error=result.error,
    )


# =============================================================================
# 7.3.1 -- Health information request
#          POST /data-flow/v3/health-information/request
# =============================================================================

def _validate_consent_usable(consent_id: str, date_range_from: str, date_range_to: str) -> dict[str, Any]:
    """
    Local pre-flight against our OWN artefact. See ConsentNotUsableError
    for why this is worth doing before spending a round trip.

    String comparison on ISO 8601 timestamps is deliberate and safe here:
    both sides are UTC with the same 'Z' suffix as stored by the on-fetch
    handler, and ISO 8601 in a fixed offset sorts lexicographically. It
    avoids a parse that could itself throw on an unexpected shape and turn
    a check into a crash.
    """
    artefact = hiu_repo.get_consent_artefact(consent_id)
    if artefact is None:
        raise ConsentNotUsableError(
            f"No artefact held for consent {consent_id!r}. A consent must be FETCHED "
            "(section 6 on-fetch) before a data request can cite it -- a consent showing "
            "GRANTED in the Consent Manager is not enough on its own."
        )

    status = artefact.get("status")
    if status != hiu_repo.CONSENT_GRANTED:
        raise ConsentNotUsableError(
            f"Consent {consent_id!r} is {status!r}, not GRANTED -- no data request can be made under it."
        )

    permission_from = artefact.get("permissionFrom")
    permission_to = artefact.get("permissionTo")
    if permission_from and date_range_from < permission_from:
        raise ConsentNotUsableError(
            f"Requested range starts {date_range_from}, before consent {consent_id!r}'s "
            f"approved window opens at {permission_from}."
        )
    if permission_to and date_range_to > permission_to:
        raise ConsentNotUsableError(
            f"Requested range ends {date_range_to}, after consent {consent_id!r}'s "
            f"approved window closes at {permission_to}."
        )

    return artefact


def request_health_information(
    settings: Settings,
    *,
    hiu_id: str,
    consent_id: str,
    hip_id: str | None,
    date_range_from: str,
    date_range_to: str,
    patient_id: str | None = None,
    alert_event_id: str | None = None,
) -> AbdmResult:
    """
    Starts a §7 transfer for an already-GRANTED, already-fetched consent.

    Generates a FRESH ECDH key pair and nonce for this one transaction --
    never reused, per Fidelius's forward-secrecy design. The private half
    goes only into the pending row, because the HIP's push (which arrives
    on a completely separate connection, minutes later) cannot be
    decrypted without it, and ABDM never sends it back to us.

    dataPushUrl is built from settings.abdm_callback_url on EVERY call, not
    cached at import, so a changed tunnel URL takes effect without a
    reload -- and it points at THIS app's own push route, which is the
    whole point of P20: the records come back to the locker, not to a
    backend the locker happens to be mounted inside.

    Raises ConsentNotUsableError before making any call when our own
    artefact already rules the request out.
    """
    artefact = _validate_consent_usable(consent_id, date_range_from, date_range_to)

    # patient_id IS NOT OPTIONAL IN PRACTICE, whatever the signature says --
    # derived from the artefact whenever a caller omits it, because every
    # query over stored records is keyed on it. A transfer written with a
    # NULL patient_id is invisible to get_records_for_patient() AND, far
    # worse, invisible to erase_health_information_for_patient(), so an
    # opt-out would silently leave those records behind. Found live
    # 2026-09-23: four transfers arrived NULL via the manual
    # /phr/data-flow/request route, which has no patient to pass. Resolved
    # here rather than at each call site so no future caller can reopen it.
    if not patient_id:
        patient_id = artefact.get("patientId")

    # Trust this HIP's bridge to push to us, BEFORE the request goes out --
    # the push can land within seconds and is signed with the HIP's own
    # client id, not ours. See hip_trust.py for why this is resolved from
    # ABDM's registry per request rather than configured up front.
    hip_bridge_id = hip_trust.trust_bridge_for_facility(settings, hip_id) if hip_id else None

    key_material = generate_key_material()
    request_id = generate_request_id()

    hiu_repo.create_pending(
        request_id,
        hiu_repo.KIND_HI_REQUEST,
        patient_id=patient_id,
        hiu_id=hiu_id,
        hip_id=hip_id,
        consent_id=consent_id,
        alert_event_id=alert_event_id,
        detail={
            "keyMaterial": key_material,
            "dateRange": {"from": date_range_from, "to": date_range_to},
            # Persisted so a restart mid-transfer can re-trust this bridge
            # from the database instead of re-querying ABDM.
            "hipBridgeId": hip_bridge_id,
        },
    )

    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/data-flow/v3/health-information/request"
    data_push_url = f"{settings.abdm_callback_url.rstrip('/')}/api/v3/hiu/health-information/push"

    payload = {
        "hiRequest": {
            "consent": {"id": consent_id},
            "dateRange": {"from": date_range_from, "to": date_range_to},
            "dataPushUrl": data_push_url,
            "keyMaterial": {
                "cryptoAlg": "ECDH",
                "curve": "Curve25519",
                "dhPublicKey": {
                    "expiry": generate_expiry_time(minutes=_KEY_EXPIRY_MINUTES),
                    "parameters": "Curve25519/32byte random key",
                    # RAW, not X.509-wrapped -- the format proven live
                    # against the sandbox. to_x509_public_key() exists in
                    # abdm_core.fidelius for the inbound direction.
                    "keyValue": key_material["public_key"],
                },
                "nonce": key_material["nonce"],
            },
        }
    }

    headers = _requester_headers(settings.abdm_x_cm_id, request_id=request_id, hiu_id=hiu_id)

    result = _execute(
        "health-information-request", url, headers, payload, "Health information request"
    )

    if not result.ok:
        hiu_repo.update_pending(
            request_id,
            state=hiu_repo.FAILED,
            failure_reason=result.error or f"health information request returned {result.status_code}",
        )

    return AbdmResult(
        status_code=result.status_code,
        body={"requestId": request_id, "response": result.body},
        error=result.error,
    )


# =============================================================================
# 6.x -- Consent notify ack  --  POST /consent/v3/request/hiu/on-notify
# =============================================================================

def send_consent_hiu_on_notify(
    settings: Settings,
    *,
    acknowledgements: list[dict[str, str]],
    request_id: str | None,
) -> AbdmResult:
    """
    Acknowledges the section 6 consent-notify callback.

    The acknowledgement is a LIST, one {"status", "consentId"} per
    artefact carried in the notify -- a single notification can grant more
    than one HIP's artefact at once, and the payload has no top-level
    consentId to ack instead.

    request_id is the REQUEST-ID header from the INBOUND callback being
    acknowledged, echoed back as response.requestId. Our own REQUEST-ID
    for this outbound call is fresh, as always.

    No pending row: an ack has no answer to correlate.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request/hiu/on-notify"
    payload = {
        "acknowledgement": acknowledgements,
        "response": {"requestId": request_id},
    }
    headers = _requester_headers(settings.abdm_x_cm_id, request_id=generate_request_id())

    return _execute(
        "consent-hiu-on-notify", url, headers, payload, "Consent HIU on-notify ack"
    )


# =============================================================================
# 7.3.5 -- Receipt outcome  --  POST /data-flow/v3/health-information/notify
# =============================================================================

def send_health_information_notify(
    settings: Settings,
    *,
    consent_id: str | None,
    transaction_id: str,
    hip_id: str | None,
    done_at: str,
    session_status: str,
    status_responses: list[dict[str, Any]],
    notifier_id: str | None,
) -> AbdmResult:
    """
    Tells ABDM how a transfer ended, once the LAST page has landed.

    notifier.type is always "HIU" here -- this module only ever acts as
    the receiving side. statusNotification.hipId stays the HIP's own id
    regardless of who is calling, which is a real asymmetry in ABDM's
    shape, not a mistake.

    sessionStatus vocabulary is role-specific: RECEIVED/FAILED for the
    HIU side (the HIP side uses TRANSFERRED/FAILED). Sending the HIP's
    vocabulary here would be wrong even though the payload would validate.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/data-flow/v3/health-information/notify"
    payload = {
        "notification": {
            "consentId": consent_id,
            "transactionId": transaction_id,
            "doneAt": done_at,
            "notifier": {"type": "HIU", "id": notifier_id},
            "statusNotification": {
                "sessionStatus": session_status,
                "hipId": hip_id,
                "statusResponses": status_responses,
            },
        }
    }
    headers = _requester_headers(settings.abdm_x_cm_id, request_id=generate_request_id())

    return _execute(
        "health-information-notify", url, headers, payload, "Health information receipt notify"
    )
