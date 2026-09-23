"""
Inbound ABDM callbacks for the locker's own HIU role: section 6 consent
(on-init, notify, on-fetch) and section 7 data flow (on-request, push).

WHAT THIS FIXES (P20). These five callbacks used to belong exclusively to
repo/server/callbacks/, because the PHR ran mounted inside that backend
under one shared client id. The consequence was concrete and was observed
live: a locker alert reached CONSENT_REQUESTED and stopped there forever,
because the consent chain ran entirely in repo/ and nothing carried its
outcome back to the alert that started it. The locker could raise a
consent and never learn it had been granted.

Here the whole chain closes locally. Every outbound call recorded an
alert_event_id on its pending row (hiu_client.py), so each callback can
advance the exact locker_alert that caused it:

    8.3.11 alert -> consent init      -> on-init   (consentRequestId)
                 -> patient/policy    -> notify    (GRANTED + artefacts)
                 -> consent fetch     -> on-fetch  (artefact stored)
                 -> HI request        -> on-request(transactionId)
                 -> HIP pushes data   -> push      (decrypt + store)

EVERY HANDLER IS DEFENSIVE ABOUT SHAPE and never raises: an exception in
a callback handler would turn into a non-2xx back to ABDM, which
redelivers, which achieves nothing if the payload is genuinely malformed.
Failures are logged and recorded on the alert instead, so a stalled flow
is explainable rather than merely absent.

CORRELATION IS A SECURITY CHECK, NOT JUST BOOKKEEPING. The route already
requires a validly ABDM-signed JWT, but that alone does not stop a
correctly-signed callback about a consent we never asked for. Each
handler additionally requires a pending row it can match, and the
on-fetch handler requires the consentId in the payload to equal the one
we actually requested -- so an artefact we did not ask for is rejected,
not stored.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from abdm_core.fidelius import decrypt_health_data, from_x509_public_key
from abdm_core.http import generate_safe_past_timestamp, generate_timestamp
from abdm_core.observability.flow_logger import log_error, log_phase, log_waiting

from aegle_phr.phr import hiu_client
from aegle_phr.phr import locker_hiu_repository as hiu_repo
from aegle_phr.phr import locker_repository as alerts
from aegle_phr.phr import retention
from aegle_phr.settings import Settings


def _as_dict(value: Any) -> dict[str, Any]:
    """Every payload field is treated as absent unless it is really a dict."""
    return value if isinstance(value, dict) else {}


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _advance_alert(event_id: str | None, state: str, **fields: Any) -> None:
    """Advances the alert an outbound call was made for, if there was one."""
    if not event_id:
        return
    try:
        alerts.update_alert_state(event_id, state, **fields)
    except Exception as exc:  # bookkeeping must never break a callback
        log_error(f"Could not advance alert {event_id} to {state}: {type(exc).__name__}: {exc}")


# =============================================================================
# 6.x -- consent request on-init
# =============================================================================

def handle_consent_request_on_init(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    ABDM acknowledging our consent init and telling us the real
    consentRequest.id.

    Confirmed shape:
        {"consentRequest": {"id": ...}, "error": null,
         "response": {"requestId": <our REQUEST-ID>}}

    Records the consentRequestId against our pending row so the later
    notify -- which arrives keyed by consentRequestId, not by our own
    REQUEST-ID -- can find its way back here. No outbound call: from here
    we wait for the patient, or for the auto-approval policy.
    """
    body = _as_dict(payload)
    log_phase("Consent init acknowledged by ABDM (POST /api/v3/hiu/consent/request/on-init)")

    request_id = _as_dict(body.get("response")).get("requestId")
    if not request_id:
        log_error("on-init callback has no response.requestId -- cannot correlate to a consent we raised.")
        return

    pending = hiu_repo.get_pending(request_id)
    if pending is None:
        log_error(f"on-init callback for requestId={request_id!r} matches no consent request we made -- ignoring.")
        return

    error = body.get("error")
    if error:
        log_error(f"Consent init rejected by ABDM: {error}")
        hiu_repo.update_pending(request_id, state=hiu_repo.FAILED, failure_reason=json.dumps(error, default=str))
        _advance_alert(pending.get("alertEventId"), alerts.ALERT_FAILED,
                       failure_reason=f"consent init rejected: {error}")
        return

    consent_request_id = _as_dict(body.get("consentRequest")).get("id")
    if not consent_request_id:
        log_error(f"on-init callback for requestId={request_id!r} has no consentRequest.id -- nothing to record.")
        return

    hiu_repo.update_pending(request_id, consent_request_id=consent_request_id)
    _advance_alert(pending.get("alertEventId"), alerts.ALERT_CONSENT_REQUESTED,
                   consent_request_id=consent_request_id)

    log_phase(f"consentRequestId {consent_request_id} recorded for requestId {request_id}")
    log_waiting("Waiting for this consent request to be approved (patient action, or the locker's auto-approval policy)")


# =============================================================================
# 6.x -- consent request notify
# =============================================================================

def handle_consent_request_notify(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    The patient's decision (or the auto-approval policy's).

    Confirmed shape:
        {"notification": {"consentRequestId": ..., "status": "GRANTED",
         "reason": null, "consentArtefacts": [{"id": ...}]}}

    On GRANTED: fetches every artefact listed -- there can be more than
    one, a multi-HIP grant -- then acknowledges. On any other status no
    fetch happens, but the callback is STILL acknowledged: ABDM asked, and
    leaving it unacked just means redelivery.

    The ack is sent LAST, after the fetches are dispatched, so a failure
    to fetch cannot be hidden behind a successful ack.
    """
    body = _as_dict(payload)
    log_phase("Consent decision received from ABDM (POST /api/v3/hiu/consent/request/notify)")

    notification = _as_dict(body.get("notification"))
    consent_request_id = notification.get("consentRequestId")
    if not consent_request_id:
        log_error("Consent notify has no notification.consentRequestId -- cannot process.")
        return

    status = notification.get("status")
    artefacts = notification.get("consentArtefacts") or []
    if not isinstance(artefacts, list):
        artefacts = []

    pending = hiu_repo.find_pending_by_consent_request(consent_request_id)
    if pending is None:
        log_error(
            f"Consent notify for consentRequestId={consent_request_id!r} matches no consent request we "
            "raised -- acknowledging it so ABDM stops redelivering, but fetching nothing."
        )

    hiu_id = (pending or {}).get("hiuId") or settings.abdm_health_locker_id
    patient_id = (pending or {}).get("patientId")
    alert_event_id = (pending or {}).get("alertEventId")

    log_phase(f"consentRequestId {consent_request_id} is {status} with {len(artefacts)} artefact(s)")

    if status == "GRANTED":
        for artefact in artefacts:
            consent_id = _as_dict(artefact).get("id")
            if not consent_id:
                continue
            # Each artefact gets its own fetch AND its own try/except: a
            # multi-HIP grant must not lose every other hospital's
            # records because one fetch failed.
            try:
                result = hiu_client.fetch_consent(
                    settings,
                    hiu_id=hiu_id,
                    consent_id=consent_id,
                    patient_id=patient_id,
                    alert_event_id=alert_event_id,
                )
                if not result.ok:
                    log_error(f"Consent fetch for {consent_id} returned {result.status_code}: {result.error}")
            except Exception as exc:
                log_error(f"Consent fetch for {consent_id} failed: {type(exc).__name__}: {exc}")
    elif status in ("DENIED", "REVOKED", "EXPIRED"):
        reason = notification.get("reason")
        _advance_alert(alert_event_id, alerts.ALERT_FAILED,
                       failure_reason=f"consent {status}" + (f": {reason}" if reason else ""))
        for artefact in artefacts:
            consent_id = _as_dict(artefact).get("id")
            if not consent_id:
                continue
            hiu_repo.set_consent_status(consent_id, status)
            # REVOKED/EXPIRED end our entitlement to hold what we already
            # collected under this consent, so the records go now rather
            # than waiting for a sweep. DENIED needs no erasure -- nothing
            # was ever granted, so nothing was ever collected -- but it
            # costs nothing to run and is safer than reasoning about which
            # statuses can and cannot have data behind them.
            retention.erase_for_consent(consent_id, f"consent {status}")

    acknowledgements = [
        {"status": "OK", "consentId": _as_dict(a).get("id")}
        for a in artefacts
        if _as_dict(a).get("id")
    ]
    try:
        hiu_client.send_consent_hiu_on_notify(
            settings, acknowledgements=acknowledgements, request_id=request_id_header
        )
    except Exception as exc:
        log_error(f"Consent notify ack failed: {type(exc).__name__}: {exc}")


# =============================================================================
# 6.x -- consent on-fetch
# =============================================================================

def handle_consent_on_fetch(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    The full artefact, and the point at which a data request becomes
    legal.

    Confirmed shape:
        {"consent": {"status": ..., "consentDetail": {...}, "signature": ...},
         "error": null, "response": {"requestId": <our REQUEST-ID>}}

    Stores the artefact, then CHAINS STRAIGHT INTO THE DATA REQUEST when
    this fetch belongs to a locker alert. That chaining is the whole point
    of P20: before it, the alert stopped at CONSENT_REQUESTED and a human
    had to notice.
    """
    body = _as_dict(payload)
    log_phase("Full consent artefact received from ABDM (POST /api/v3/hiu/consent/on-fetch)")

    error = body.get("error")
    if error:
        log_error(f"Consent fetch failed per ABDM: {error}")
        return

    consent = _as_dict(body.get("consent"))
    detail = _as_dict(consent.get("consentDetail"))
    consent_id = detail.get("consentId")
    if not consent_id:
        log_error("on-fetch callback has no consent.consentDetail.consentId -- nothing to store.")
        return

    request_id = _as_dict(body.get("response")).get("requestId")
    pending = hiu_repo.get_pending(request_id) if request_id else None
    if pending is None:
        log_error(
            f"on-fetch callback for consentId={consent_id} matches no fetch we made "
            f"(requestId={request_id!r}) -- rejecting, not storing."
        )
        return
    if pending.get("consentId") != consent_id:
        log_error(
            f"on-fetch callback carries consentId={consent_id} but we requested "
            f"{pending.get('consentId')!r} for requestId={request_id} -- rejecting, not storing."
        )
        return

    permission = _as_dict(detail.get("permission"))
    date_range = _as_dict(permission.get("dateRange"))

    artefact = hiu_repo.upsert_consent_artefact(
        consent_id,
        consent_request_id=pending.get("consentRequestId"),
        patient_id=_as_dict(detail.get("patient")).get("id") or pending.get("patientId"),
        hiu_id=_as_dict(detail.get("hiu")).get("id") or pending.get("hiuId"),
        hip_id=_as_dict(detail.get("hip")).get("id") or pending.get("hipId"),
        status=consent.get("status") or hiu_repo.CONSENT_GRANTED,
        hi_types=detail.get("hiTypes"),
        permission_from=_parse_iso(date_range.get("from")),
        permission_to=_parse_iso(date_range.get("to")),
        data_erase_at=_parse_iso(permission.get("dataEraseAt")),
        artefact=detail,
        signature=consent.get("signature"),
    )
    hiu_repo.update_pending(request_id, state=hiu_repo.RESOLVED)

    alert_event_id = pending.get("alertEventId")
    _advance_alert(alert_event_id, alerts.ALERT_CONSENT_GRANTED, consent_id=consent_id)
    log_phase(f"Consent artefact {consent_id} stored (status={artefact.get('status')})")

    if artefact.get("status") != hiu_repo.CONSENT_GRANTED:
        log_phase(f"Consent {consent_id} is not GRANTED -- no data request will be made under it.")
        return

    _request_data_for_artefact(settings, artefact, alert_event_id)


def _request_data_for_artefact(
    settings: Settings, artefact: dict[str, Any], alert_event_id: str | None
) -> None:
    """
    Fires the §7 data request for a freshly stored artefact.

    THE DATE RANGE COMES FROM THE ARTEFACT ITSELF, not from our own
    preferred look-back. ABDM rejects a request whose range falls outside
    the approved window (ABDM-1063), and the approved window is whatever
    the patient or the policy actually granted -- which may be narrower
    than what we asked for. Asking for exactly what was granted is the
    only range guaranteed to be accepted.
    """
    consent_id = artefact.get("consentId")
    date_from = artefact.get("permissionFrom")
    date_to = artefact.get("permissionTo")
    if not (consent_id and date_from and date_to):
        log_error(
            f"Cannot request data for consent {consent_id!r}: artefact has no usable "
            f"permission window ({date_from!r} -> {date_to!r})."
        )
        _advance_alert(alert_event_id, alerts.ALERT_FAILED,
                       failure_reason="granted artefact carried no usable permission window")
        return

    try:
        result = hiu_client.request_health_information(
            settings,
            hiu_id=artefact.get("hiuId") or settings.abdm_health_locker_id,
            consent_id=consent_id,
            hip_id=artefact.get("hipId"),
            date_range_from=date_from,
            date_range_to=date_to,
            patient_id=artefact.get("patientId"),
            alert_event_id=alert_event_id,
        )
    except hiu_client.ConsentNotUsableError as exc:
        log_error(f"Data request for consent {consent_id} ruled out locally: {exc}")
        _advance_alert(alert_event_id, alerts.ALERT_FAILED, failure_reason=str(exc))
        return
    except Exception as exc:
        log_error(f"Data request for consent {consent_id} failed: {type(exc).__name__}: {exc}")
        _advance_alert(alert_event_id, alerts.ALERT_FAILED, failure_reason=str(exc))
        return

    if result.ok:
        _advance_alert(
            alert_event_id,
            alerts.ALERT_DATA_REQUESTED,
            consent_id=consent_id,
            health_information_request_id=(result.body or {}).get("requestId"),
        )
        log_phase(f"Data request sent for consent {consent_id} ({date_from} -> {date_to})")
    else:
        reason = result.error or f"health information request returned {result.status_code}"
        _advance_alert(alert_event_id, alerts.ALERT_FAILED, failure_reason=reason)
        log_error(f"Data request for consent {consent_id} not accepted: {reason}")


# =============================================================================
# 7.3.2 -- health information on-request
# =============================================================================

def handle_health_information_on_request(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    ABDM acknowledging our data request and naming the transactionId.

    Confirmed shape:
        {"hiRequest": {"transactionId": ..., "sessionStatus": "REQUESTED"},
         "response": {"requestId": <our REQUEST-ID>}}

    The transactionId matters because the HIP's push arrives keyed by it
    and by nothing else -- it never carries our REQUEST-ID.
    """
    body = _as_dict(payload)
    log_phase("Data request acknowledged by ABDM (POST /api/v3/hiu/health-information/on-request)")

    request_id = _as_dict(body.get("response")).get("requestId")
    if not request_id:
        log_error("on-request callback has no response.requestId -- cannot correlate to a data request we made.")
        return

    pending = hiu_repo.get_pending(request_id)
    if pending is None:
        log_error(f"on-request callback for requestId={request_id!r} matches no data request we made -- ignoring.")
        return

    error = body.get("error")
    if error:
        log_error(f"Data request rejected by ABDM: {error}")
        hiu_repo.update_pending(request_id, state=hiu_repo.FAILED, failure_reason=json.dumps(error, default=str))
        _advance_alert(pending.get("alertEventId"), alerts.ALERT_FAILED,
                       failure_reason=f"data request rejected: {error}")
        return

    hi_request = _as_dict(body.get("hiRequest"))
    transaction_id = hi_request.get("transactionId")
    if not transaction_id:
        log_error(f"on-request callback for requestId={request_id} has no hiRequest.transactionId.")
        return

    existing = hiu_repo.find_pending_by_transaction(transaction_id)
    if existing is not None and existing.get("requestId") != request_id:
        # Two different requests claiming one transactionId means one of
        # the correlations is wrong. Refusing is right: a mis-linked
        # transaction decrypts a push with the wrong key material.
        log_error(
            f"transactionId {transaction_id} is already linked to requestId "
            f"{existing.get('requestId')!r} -- refusing to relink it to {request_id}."
        )
        return

    hiu_repo.update_pending(request_id, transaction_id=transaction_id)
    log_phase(
        f"transactionId {transaction_id} recorded for requestId {request_id} "
        f"(sessionStatus={hi_request.get('sessionStatus')})"
    )
    log_waiting("Waiting for the HIP to push encrypted records directly to our dataPushUrl")


# =============================================================================
# 7.3.3 -- the HIP's direct data push  (NOT via the gateway)
# =============================================================================

def _compute_checksum(encrypted_content: str) -> str:
    """MD5 hex digest of the encrypted content, as ABDM's HIPs compute it."""
    return hashlib.md5(encrypted_content.encode("utf-8")).hexdigest()


def _authorized_care_contexts(artefact: dict[str, Any] | None) -> set[str]:
    """
    The care contexts the stored artefact actually covers.

    Anything outside this set is refused WITHOUT being decrypted. A HIP
    that pushes more than the consent granted does not get its extra
    records stored just because it managed to encrypt them to our key.
    """
    if not artefact:
        return set()
    detail = artefact.get("artefact")
    if not isinstance(detail, dict):
        return set()
    refs = set()
    for care_context in detail.get("careContexts") or []:
        if isinstance(care_context, dict) and care_context.get("careContextReference"):
            refs.add(care_context["careContextReference"])
    return refs


def _decrypt_entries(
    entries: list[Any],
    authorized_refs: set[str],
    consent_id: str | None,
    hip_public_key_raw: Any,
    our_key_material: dict[str, Any],
    hip_key_material: dict[str, Any],
) -> dict[str, Any]:
    """
    Checksum-verifies, scope-checks and decrypts every entry in one push.

    A failure on one entry is recorded against that care context and the
    rest continue -- one corrupt record must not cost a patient the other
    nine.
    """
    results: dict[str, Any] = {}

    for entry in entries:
        entry = _as_dict(entry)
        reference = entry.get("careContextReference")
        content = entry.get("content")
        claimed_checksum = entry.get("checksum")

        if not reference or not content:
            log_error("Skipping a push entry with no careContextReference/content.")
            continue

        def record(status: str, description: str, bundle: Any = None) -> None:
            results[reference] = {
                "hi_status": status,
                "description": description,
                "bundle": bundle,
                "received_at": generate_timestamp(),
            }

        if reference not in authorized_refs:
            log_error(
                f"Refusing care context {reference} -- not covered by consent {consent_id!r}. "
                "Not decrypted, not stored."
            )
            record("ERRORED", "Care context not covered by the granted consent")
            continue

        actual_checksum = _compute_checksum(content)
        if claimed_checksum and actual_checksum != claimed_checksum:
            log_error(f"Checksum mismatch for {reference}: claimed {claimed_checksum}, computed {actual_checksum}.")
            record("ERRORED", "Checksum mismatch")
            continue

        if hip_public_key_raw is None:
            record("ERRORED", "Could not decode the HIP's public key")
            continue

        try:
            plaintext = decrypt_health_data(
                ciphertext=content,
                sender_private_key=our_key_material.get("private_key"),
                sender_nonce=our_key_material.get("nonce"),
                requester_public_key=hip_public_key_raw,
                requester_nonce=hip_key_material.get("nonce"),
            )
            record("OK", "Received and decrypted successfully", json.loads(plaintext))
        except Exception as exc:
            log_error(f"Decryption failed for {reference}: {type(exc).__name__}: {exc}")
            record("ERRORED", f"Decryption failed: {exc}")

    return results


def handle_health_information_push(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    The HIP's encrypted records, pushed straight to us.

    Confirmed shape:
        {"pageNumber": 0, "pageCount": 1, "transactionId": ...,
         "entries": [{"content", "media", "checksum", "careContextReference"}],
         "keyMaterial": {"cryptoAlg", "curve", "dhPublicKey", "nonce"}}

    NOT DELIVERED THROUGH THE GATEWAY, unlike every other callback here --
    the HIP posts directly to the dataPushUrl we supplied on the request.

    ONE PAGE PER CARE CONTEXT is the normal case, not an edge case: each
    page carries its own freshly generated keyMaterial, because reusing
    one AES key+IV across every entry would be a real weakness. So this
    handler runs several times per transfer, merges each page, and only
    notifies ABDM once the LAST page has landed.
    """
    body = _as_dict(payload)
    log_phase("Encrypted records pushed by the HIP (POST /api/v3/hiu/health-information/push)")

    transaction_id = body.get("transactionId")
    if not transaction_id:
        log_error("Data push has no transactionId -- cannot correlate to a data request we made.")
        return

    entries = body.get("entries") or []
    if not isinstance(entries, list):
        entries = []
    hip_key_material = _as_dict(body.get("keyMaterial"))

    pending = hiu_repo.find_pending_by_transaction(transaction_id)
    if pending is None:
        # No stage-2/3 guessing fallback here, deliberately. repo/'s
        # version needed one because its on-request acks sometimes never
        # arrived at all; if that recurs here it should be diagnosed with
        # the correlation data this app now keeps, not papered over by
        # matching a push to whichever request looks plausible.
        log_error(
            f"Data push for transactionId {transaction_id} matches no data request we made -- "
            "refusing to decrypt it."
        )
        return

    our_key_material = _as_dict((pending.get("detail") or {}).get("keyMaterial"))
    consent_id = pending.get("consentId")
    hip_id = pending.get("hipId")
    hiu_id = pending.get("hiuId") or settings.abdm_health_locker_id
    alert_event_id = pending.get("alertEventId")

    artefact = hiu_repo.get_consent_artefact(consent_id) if consent_id else None
    authorized_refs = _authorized_care_contexts(artefact)
    if not authorized_refs:
        log_error(
            f"No stored artefact (or no careContexts on it) for consentId={consent_id!r} -- "
            "every entry in this push will be refused as out of scope."
        )

    try:
        hip_public_key_raw = from_x509_public_key(
            _as_dict(hip_key_material.get("dhPublicKey")).get("keyValue")
        )
    except Exception as exc:
        log_error(f"Could not decode the HIP's public key for {transaction_id}: {exc}")
        hip_public_key_raw = None

    page_results = _decrypt_entries(
        entries, authorized_refs, consent_id, hip_public_key_raw, our_key_material, hip_key_material
    )

    page_number = body.get("pageNumber")
    page_count = body.get("pageCount")

    record = hiu_repo.merge_health_information(
        transaction_id,
        care_contexts=page_results,
        page_number=page_number,
        page_count=page_count,
        request_id=pending.get("requestId"),
        consent_id=consent_id,
        patient_id=pending.get("patientId"),
        hip_id=hip_id,
    )
    merged = record.get("careContexts") or {}
    log_phase(
        f"Stored {len(page_results)} care context(s) from page "
        f"{(page_number + 1) if isinstance(page_number, int) else '?'}/{page_count or '?'} -- "
        f"{len(merged)} accumulated for transactionId {transaction_id}"
    )

    if not hiu_repo.is_transfer_complete(record):
        remaining = (page_count or 0) - (page_number or 0) - 1
        log_waiting(f"Waiting for {remaining} more page(s) before notifying ABDM for {transaction_id}")
        return

    any_ok = any(r.get("hi_status") == "OK" for r in merged.values())
    session_status = "RECEIVED" if any_ok else "FAILED"
    status_responses = [
        {
            "careContextReference": ref,
            "hiStatus": result.get("hi_status"),
            "description": result.get("description"),
        }
        for ref, result in merged.items()
    ]

    hiu_repo.merge_health_information(
        transaction_id,
        status="OK" if any_ok else "ERRORED",
        failure_reason=None if any_ok else "no care context was received and decrypted successfully",
    )

    # P20 -- now that this transfer is complete, drop any older copy of the
    # care contexts it just delivered. One visit produces a LINK and a DATA
    # alert, each raising its own consent and its own data request, so the
    # same bundle arrives twice; the read already hides the older copy, but
    # nothing would ever ERASE it, because the consent behind it stays
    # valid. Runs only on a successful, complete transfer -- pruning on a
    # failed one would destroy good data in favour of nothing.
    if any_ok:
        try:
            pruned = hiu_repo.prune_superseded(transaction_id)
            if pruned.get("careContextsPruned"):
                log_phase(
                    f"Pruned {pruned['careContextsPruned']} superseded care context copy/copies "
                    f"from {pruned['prunedFrom']} earlier transfer(s)"
                )
        except Exception as exc:  # housekeeping must never fail a transfer
            log_error(f"Could not prune superseded copies for {transaction_id}: {type(exc).__name__}: {exc}")
    hiu_repo.update_pending(
        pending["requestId"],
        state=hiu_repo.RESOLVED if any_ok else hiu_repo.FAILED,
        failure_reason=None if any_ok else "transfer completed with no usable care context",
    )
    _advance_alert(
        alert_event_id,
        alerts.ALERT_DATA_RECEIVED if any_ok else alerts.ALERT_FAILED,
        failure_reason=None if any_ok else "transfer completed with no usable care context",
    )

    try:
        result = hiu_client.send_health_information_notify(
            settings,
            consent_id=consent_id,
            transaction_id=transaction_id,
            hip_id=hip_id,
            done_at=generate_safe_past_timestamp(),
            session_status=session_status,
            status_responses=status_responses,
            notifier_id=hiu_id,
        )
        if not result.ok:
            log_error(f"Receipt notify returned {result.status_code}: {result.error}")
    except Exception as exc:
        log_error(f"Receipt notify failed: {type(exc).__name__}: {exc}")

    if any_ok:
        log_phase(f"Records received and decrypted -- transfer {transaction_id} complete.")
    else:
        log_error(f"Transfer {transaction_id} completed with nothing usable -- see the status responses above.")
