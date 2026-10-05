"""
P22 -- real per-callback logic for Scan & Share's one inbound callback,
`on_share` (POST /api/v3/hiu/patient/on-share).

Same shape as uil_services.py: a plain, sync `def` that never raises,
called from router.py AFTER dispatch() has already archived the payload
verbatim. No outbound ABDM call is made here -- router.py's generic
{"status": "OK"} response is the acknowledgement.

=============================================================================
THIS HANDLER IS WRITTEN FOR A PAYLOAD NOBODY HAS EVER SEEN
=============================================================================
Every other callback in this package was built against a documented
example. This one has none: the path itself came from a task spec rather
than a captured call, and no sample body for it exists in the spec, in
either Postman collection, or in NHA's reference wrapper -- which
implements only the HIP side of Scan & Share, never the patient side.

So this does not parse a shape. It goes looking, in a deliberate order,
and says loudly what it found:

  CORRELATION, in order:
    1. response.requestId    -- the envelope every other callback here uses
    2. requestId             -- the same field one level up, in case this
                                callback skips the envelope
    3. abhaAddress + context -- the fallback, matched against the newest
                                not-yet-tokened row for that patient

  THE TOKEN, in order:
    1. acknowledgement.profile.tokenNumber   -- exactly what repo/'s P21
                                                sends the CM; the CM may
                                                pass it straight through
    2. profile.tokenNumber                   -- the same, unwrapped
    3. tokenNumber                           -- flat

WHEN NO TOKEN IS FOUND ANYWHERE, THAT IS THE DELIVERABLE, not a failure to
paper over. The payload is stored on the row and a loud log line records
what arrived, because "the callback fires but carries no token" and "the
callback never fires at all" are different answers to the open question in
aegle_phr/phr/profile_share.py's banner, and only the log can tell them
apart afterwards.

PRECEDENCE AGAINST THE POLL. getTokenDetails (Candidate B) writes the same
row. Whichever mechanism arrives first wins and stamps `source`; the later
one does not overwrite a token that is already there. The UI shows
whichever landed. That is a deliberate choice under uncertainty -- see the
route's own comment in api.py.
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr.profile_share_repository import find_latest_pending, update_by_request_id
from aegle_phr.settings import Settings


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_string(*candidates: Any) -> str | None:
    """
    The first candidate that is a non-empty scalar, as a string.

    Accepts a number as well as a string on purpose: a token number is a
    number in every human sense, and nothing guarantees the CM sends it
    quoted. P21 sends it zero-padded as a string; a relay that re-encoded
    it as JSON could easily drop the quotes and the padding both.
    """
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return str(candidate)
    return None


def _extract_token(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Digs a token number and expiry out of whichever of the three candidate
    shapes this payload turns out to be. Returns (token_number, expiry),
    either of which may be None.
    """
    acknowledgement = _as_dict(payload.get("acknowledgement"))
    ack_profile = _as_dict(acknowledgement.get("profile"))
    flat_profile = _as_dict(payload.get("profile"))

    token = _first_string(
        ack_profile.get("tokenNumber"),
        flat_profile.get("tokenNumber"),
        payload.get("tokenNumber"),
    )
    expiry = _first_string(
        ack_profile.get("expiry"),
        flat_profile.get("expiry"),
        payload.get("expiry"),
    )
    return token, expiry


def _extract_identity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    abhaAddress and context, for the fallback correlation -- looked for in
    the same three nesting depths as the token, since a payload that put
    the token in an unexpected place will have put these there too.
    """
    acknowledgement = _as_dict(payload.get("acknowledgement"))
    ack_profile = _as_dict(acknowledgement.get("profile"))
    flat_profile = _as_dict(payload.get("profile"))
    meta = _as_dict(payload.get("metaData"))

    abha_address = _first_string(
        acknowledgement.get("abhaAddress"),
        payload.get("abhaAddress"),
        _as_dict(flat_profile.get("patient")).get("abhaAddress"),
    )
    context = _first_string(
        ack_profile.get("context"),
        flat_profile.get("context"),
        meta.get("context"),
        payload.get("context"),
    )
    return abha_address, context


def handle_on_share(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    Correlates an on-share callback back to the ProfileShareRequest row the
    /phr/scan-share/share route created, and records whatever token it
    carries.

    UNCONFIRMED throughout -- see this module's banner. Nothing below
    assumes a field exists.
    """
    if not isinstance(payload, dict):
        log_error(
            "Scan & Share on_share payload is not a dict -- cannot process. "
            f"Got {type(payload).__name__}. It is still archived in callback_log; "
            "read it there, this is the first sighting of this callback's shape."
        )
        return

    # --- correlate -------------------------------------------------------
    our_request_id = _first_string(
        _as_dict(payload.get("response")).get("requestId"),
        payload.get("requestId"),
    )
    correlation = "response.requestId"

    if our_request_id is None:
        abha_address, context = _extract_identity(payload)
        if abha_address is None:
            log_error(
                "Scan & Share on_share callback carries NEITHER a requestId NOR an abhaAddress -- "
                "nothing to correlate it to. The payload is archived in callback_log; it is the "
                f"first real sighting of this callback's shape. Keys present: {sorted(payload)}"
            )
            return
        row = find_latest_pending(abha_address, context)
        if row is None:
            log_error(
                f"Scan & Share on_share callback for {abha_address} (context={context!r}) has no "
                "requestId and matches no pending share row. Archived, not correlated."
            )
            return
        our_request_id = row["requestId"]
        correlation = "abhaAddress+context fallback"
        log_phase(
            f"Scan & Share on_share callback had no requestId -- correlated to {our_request_id} "
            f"by {correlation}. WORTH KNOWING: this callback's envelope differs from every other "
            "callback in this app."
        )

    # --- read the token --------------------------------------------------
    error = payload.get("error")
    token_number, token_expiry = _extract_token(payload)

    if error:
        update_by_request_id(our_request_id, status="ERROR", detail=payload, source="CALLBACK")
        log_error(f"Scan & Share on_share {our_request_id} returned an error: {error}")
        return

    if token_number is None:
        # NOT A SILENT FAILURE. This line is the actual finding if
        # Candidate A turns out to fire without carrying a token.
        update_by_request_id(our_request_id, status="SHARED", detail=payload, source="CALLBACK")
        log_error(
            f"Scan & Share on_share {our_request_id} arrived and was correlated ({correlation}), "
            f"but carries NO token number in any of the three shapes checked. Keys present: "
            f"{sorted(payload)}. Payload stored on the row and archived in callback_log -- read it "
            "and extend _extract_token(). The poll (getTokenDetails) is the fallback meanwhile."
        )
        return

    row = update_by_request_id(
        our_request_id,
        status="TOKEN_ISSUED",
        detail=payload,
        token_number=token_number,
        token_expiry=token_expiry,
        source="CALLBACK",
    )
    if row is None:
        log_error(f"No share row found for requestId {our_request_id} -- token {token_number} could not be stored.")
        return

    log_phase(
        f"Scan & Share on_share {our_request_id} complete: token={token_number} "
        f"expiry={token_expiry!r} (correlated by {correlation}). CANDIDATE A IS REAL."
    )
