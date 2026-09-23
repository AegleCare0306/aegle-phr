"""
What the locker is allowed to keep, and when it must let go.

THE BARGAIN. A Health Locker is entitled to STORE a patient's records for
as long as the consent behind them is valid. That is what makes it a
locker rather than a proxy: a login reads local storage, not a fresh ABDM
round trip per hospital. The other half of the bargain is that the moment
the basis for holding the data ends, the data goes -- and goes on our own
initiative, not only when someone asks.

FOUR TRIGGERS, all wired:

  1. Consent REVOKED    -- the patient withdrew it. Arrives on the section
                           6 notify callback; handled in
                           callbacks/hiu_services.handle_consent_request_notify().
  2. Consent EXPIRED    -- ABDM says so, same callback.
  3. dataEraseAt passed  -- the erase-by instruction carried inside the
                           artefact, which we agreed to when we raised the
                           consent. Nobody tells us; we sweep for it.
  4. Patient opts out   -- withdraws the locker relationship entirely.
                           Everything for that patient goes, not just one
                           consent's worth.

WHAT ERASURE DESTROYS. The decrypted FHIR bundles -- set to NULL. What
survives is a tombstone of ids and timestamps, which holds no clinical
content and exists so "did you hold my records, and when did you erase
them" has an answer. Patient-scoped erasure additionally strips
care-context references, because "attended this hospital on this date" is
health-adjacent personal data in its own right.

WHAT IT DOES NOT DO. It does not revoke anything at ABDM. A patient
revoking consent in their Consent Manager is ABDM's business; this module
reacts to that, and separately honours an opt-out recorded in this app.
The two are different events and neither implies the other.

A NOTE ON THE TWO DATE FIELDS, because they are easy to confuse and the
consequence of confusing them is total data loss:
    permission.dateRange.to -- the end of the DATA RANGE covered. The
                               locker asks for "everything up to now", so
                               this is always ~the moment of the request.
    dataEraseAt             -- the RETENTION deadline. This is the one
                               that governs erasure.
See locker_hiu_repository.find_erasable_artefacts().
"""

from datetime import datetime, timezone
from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr import locker_hiu_repository as hiu_repo
from aegle_phr.phr import locker_repository as repo


def erase_for_consent(consent_id: str, reason: str) -> dict[str, Any]:
    """
    Trigger 1 and 2: one consent's basis has ended, so everything
    collected under it goes.

    Scoped to that consent, deliberately. A patient revoking one
    hospital's consent has not withdrawn the others, and erasing more than
    was withdrawn would be its own kind of failure.
    """
    try:
        erased = hiu_repo.erase_health_information_for_consent(consent_id, reason)
    except Exception as exc:
        log_error(f"Erasure failed for consent {consent_id}: {type(exc).__name__}: {exc}")
        return {"ok": False, "consentId": consent_id, "error": str(exc)}

    if erased:
        log_phase(f"Erased {erased} transfer(s) held under consent {consent_id}: {reason}")
    return {"ok": True, "consentId": consent_id, "transfersErased": erased, "reason": reason}


def erase_for_patient(patient_id: str, locker_id: str, reason: str) -> dict[str, Any]:
    """
    Trigger 4: the patient has withdrawn from the locker entirely.

    Three things go: the record content, the artefact bodies (which name
    the specific visits), and the alert contexts (same reason). The
    patient_locker row itself STAYS, holding opt_in_state -- deleting it
    would lose the record that they opted out, and the automation would
    cheerfully re-subscribe them on next login. A row saying "this person
    said no" is not data held against their wishes; it is what honours
    them.
    """
    result: dict[str, Any] = {"ok": True, "patientId": patient_id, "reason": reason}
    try:
        result["transfersErased"] = hiu_repo.erase_health_information_for_patient(patient_id, reason)
        result["artefactsRedacted"] = hiu_repo.redact_artefacts_for_patient(
            patient_id, hiu_repo.CONSENT_REVOKED
        )
        result["alertsRedacted"] = repo.redact_alert_contexts_for_patient(patient_id)
    except Exception as exc:
        log_error(f"Erasure failed for patient {patient_id}: {type(exc).__name__}: {exc}")
        return {"ok": False, "patientId": patient_id, "error": str(exc)}

    log_phase(
        f"Erased everything held for {patient_id} in locker {locker_id}: "
        f"{result['transfersErased']} transfer(s), {result['artefactsRedacted']} artefact(s), "
        f"{result['alertsRedacted']} alert(s) -- {reason}"
    )
    return result


def sweep_expired(patient_id: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """
    Trigger 3: erase anything whose dataEraseAt has passed.

    Runs on our own initiative -- at startup, and whenever a patient's
    records are read. Reading is the right moment because it is the point
    at which we would otherwise SERVE the data: a record we are no longer
    entitled to hold must not be returned even once, and sweeping first
    guarantees it cannot be.

    Cheap by construction: the query is indexed on a timestamp and
    normally matches nothing.
    """
    now = now or datetime.now(timezone.utc)
    outcomes = []
    try:
        lapsed = hiu_repo.find_erasable_artefacts(now=now, patient_id=patient_id)
    except Exception as exc:
        log_error(f"Retention sweep could not read artefacts: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": str(exc)}

    for artefact in lapsed:
        consent_id = artefact.get("consentId")
        if not consent_id:
            continue
        outcome = erase_for_consent(
            consent_id, f"retention deadline reached (dataEraseAt {artefact.get('dataEraseAt')})"
        )
        hiu_repo.set_consent_status(consent_id, hiu_repo.CONSENT_EXPIRED)
        outcomes.append(outcome)

    if outcomes:
        log_phase(f"Retention sweep erased {len(outcomes)} lapsed consent(s)")
    return {"ok": True, "swept": len(outcomes), "consents": outcomes}
