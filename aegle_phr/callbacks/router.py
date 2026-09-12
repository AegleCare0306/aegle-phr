"""
Inbound ABDM callback routes owned by the PHR app.

=============================================================================
PATHS THIS REPO DELIBERATELY DOES NOT OWN -- READ BEFORE ADDING A ROUTE
=============================================================================
The PHR is designed to run IN THE SAME PROCESS as the existing ABDM backend
(one client ID, one callback URL, one ngrok host -- so one place for ABDM
callbacks to land). Two routers in one FastAPI app cannot both own a path:
whichever is included first wins, silently, and the other's handler simply
never runs.

These four paths are already registered and handled by the existing
backend's M3 HIU code (repo/server/callbacks/router.py, lines ~114-144).
They must NOT be added here without an explicit, deliberate decision about
which app owns the flow:

    /api/v3/hiu/consent/request/on-init
    /api/v3/hiu/consent/request/notify
    /api/v3/hiu/consent/on-fetch
    /api/v3/hiu/health-information/on-request

Adding one of them here would not fail loudly. It would produce a
consent/data flow that works in standalone PHR testing and then silently
stops working -- or worse, half-works -- the moment the two apps are
mounted together. If the PHR genuinely needs to participate in those
flows, the answer is to route them in ONE place and fan out, not to
register the path twice.
=============================================================================

Every route below is a plain `def`, not `async def`. See aegle_phr/db.py
for why (blocking DB + blocking requests -> threadpool, not event loop).
"""

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Body, Depends, Request

from abdm_core.callback_auth import verify_abdm_callback
from abdm_core.http import generate_request_id
from abdm_core.observability.flow_logger import log_error, set_correlation_id

from aegle_phr.callbacks import subscription_services, uil_services
from aegle_phr.callbacks.dispatcher import dispatch
from aegle_phr.settings import Settings

# The six callback paths this repo owns, as (path, callback_type).
# callback_type is our own short name, stored in callback_log.callback_type
# and used in log lines -- it is not an ABDM field.
#
# UNCONFIRMED: these six paths come from the task specification, not from a
# live ABDM sandbox callback we have captured. The exact PAYLOAD SHAPE of
# each is likewise unconfirmed -- which is precisely why this chunk stores
# the body verbatim as JSONB and parses nothing beyond the envelope
# requestId. on_discover/on_init/on_confirm got real per-callback handling
# in P15 (_UIL_HANDLERS below); on_share remains archive-only, no chunk has
# built it yet.
CALLBACK_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/v3/hiu/patient/care-context/on-discover", "on_discover"),
    ("/api/v3/hiu/patient/care-context/on-init", "on_init"),
    ("/api/v3/hiu/patient/care-context/on-confirm", "on_confirm"),
    ("/api/v3/hiu/patient/on-share", "on_share"),
    ("/api/v3/hiu/hiecm/subscription-requests/on-init", "subscription_on_init"),
    ("/api/v3/hiu/subscription-requests/hiu/notify", "subscription_notify"),
    # P13 -- spec 8.3.11, care-context "new LINK/DATA available" event
    # notify. A DIFFERENT path from the one directly above
    # (subscription/notify vs subscription-requests/hiu/notify) -- do not
    # conflate them, see CC_PROMPT_P13_subscription_flow_full_build.md's
    # own URL table for the full discrepancy note. Not previously
    # registered anywhere and not in FORBIDDEN_PATHS below.
    ("/api/v3/hiu/subscription/notify", "subscription_care_context_notify"),
)

# P13 -- real per-callback handling for these three callback_types, called
# AFTER dispatch() has already archived the payload (see _make_handler()'s
# own docstring for why this happens outside dispatch() itself, and
# subscription_services.py for what each of these three actually does).
# Keyed by callback_type, not path, so this stays correct even if a path
# above ever changes.
_SUBSCRIPTION_HANDLERS: dict[str, Callable[[Settings, Any, str | None], None]] = {
    "subscription_on_init": lambda settings, payload, request_id_header: subscription_services.handle_subscription_on_init(settings, payload, request_id_header),
    "subscription_notify": lambda settings, payload, request_id_header: subscription_services.handle_subscription_notify(settings, payload),
    "subscription_care_context_notify": lambda settings, payload, request_id_header: subscription_services.handle_subscription_care_context_notify(settings, payload, request_id_header),
}

# P15 -- real per-callback handling for User-Initiated Linking (spec §10),
# called the same way _SUBSCRIPTION_HANDLERS is (see _make_handler()'s own
# lookup below) -- a separate dict, not merged into _SUBSCRIPTION_HANDLERS,
# so each feature area's own callback set stays independently readable.
_UIL_HANDLERS: dict[str, Callable[[Settings, Any, str | None], None]] = {
    "on_discover": lambda settings, payload, request_id_header: uil_services.handle_on_discover(settings, payload, request_id_header),
    "on_init": lambda settings, payload, request_id_header: uil_services.handle_on_init(settings, payload, request_id_header),
    "on_confirm": lambda settings, payload, request_id_header: uil_services.handle_on_confirm(settings, payload, request_id_header),
}

# Paths listed above in the banner. Kept as data as well as prose so a test
# can assert they are absent -- see the repo README's verification notes.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "/api/v3/hiu/consent/request/on-init",
    "/api/v3/hiu/consent/request/notify",
    "/api/v3/hiu/consent/on-fetch",
    "/api/v3/hiu/health-information/on-request",
)

# ABDM's standard acknowledgement. Matches the existing backend's
# server/callbacks/utils/response.py success() exactly, so both apps ack
# identically once they share a process.
_ACK = {"status": "OK"}


def _make_handler(callback_type: str, settings: Settings):
    """
    Builds one route handler bound to a callback_type (and, since P13,
    settings -- needed by the three callback_types in
    _SUBSCRIPTION_HANDLERS, which make real outbound ABDM calls of their
    own and therefore need abdm_hiecm_base_url/abdm_x_cm_id).

    A factory, not a loop-body closure: closing over the loop variable
    directly would leave every handler pointing at the LAST callback_type
    (Python closures capture the variable, not its value).
    """

    # Annotated[Any, Body()] and not a bare `dict`: the payload shapes of
    # these seven callbacks are unconfirmed (see CALLBACK_ROUTES), so this
    # accepts ANY JSON value and stores it verbatim rather than rejecting
    # an unexpected shape with a 422 before it can be archived. A bare
    # `dict | list | None = None` annotation does NOT work here -- FastAPI
    # reads an un-annotated non-pydantic union as form data, not a body.
    def handler(
        request: Request,
        payload: Annotated[Any, Body()] = None,
    ) -> dict:
        # One correlation id per request, shared with abdm_core's
        # flow_logger so this request's log lines and its archived row can
        # be tied together afterwards.
        correlation_id = generate_request_id()
        set_correlation_id(correlation_id)

        # ABDM's envelope requestId, best-effort. A payload that is not a
        # dict (or lacks the field) is still archived -- see dispatcher.
        request_id = payload.get("requestId") if isinstance(payload, dict) else None

        dispatch(
            callback_type=callback_type,
            payload=payload,
            request_id=request_id,
            correlation_id=correlation_id,
            source_ip=request.client.host if request.client else None,
        )

        # P13/P15 -- real per-callback handling, OUTSIDE dispatch() on
        # purpose (dispatch()'s own docstring: "Don't put real business
        # logic inside dispatch() itself"). Archival above already
        # happened unconditionally; this is wrapped in its own try/except
        # so a bug in real handler logic can NEVER surface to ABDM as a
        # non-2xx -- same "never raise past the callback route" contract
        # dispatch() itself upholds, just enforced one layer up instead of
        # inside it. Two separate dicts (one per feature area), checked in
        # turn -- callback_type namespaces don't overlap between them.
        real_handler = _SUBSCRIPTION_HANDLERS.get(callback_type) or _UIL_HANDLERS.get(callback_type)
        if real_handler is not None:
            try:
                # ABDM's own REQUEST-ID header on THIS inbound callback --
                # Starlette's Headers is case-insensitive, so this reads
                # regardless of exact casing ABDM sends. Needed by the two
                # ack-sending handlers (on-init, care-context-notify) to
                # echo it back, per the confirmed live consent precedent
                # (see subscription.py's own ack_* docstrings).
                request_id_header = request.headers.get("REQUEST-ID")
                real_handler(settings, payload, request_id_header)
            except Exception as exc:
                log_error(f"Real handler for callback_type={callback_type} failed unexpectedly: {type(exc).__name__}: {exc}")

        return _ACK

    handler.__name__ = f"phr_callback_{callback_type}"
    return handler


def build_callback_router(settings: Settings) -> APIRouter:
    """
    Builds the callback router. `settings` is now genuinely used (P13) --
    the three subscription callback handlers make real outbound ABDM
    calls of their own and need it threaded through.

    NO GLOBAL STATE and no @app.on_event handlers -- a fresh APIRouter is
    constructed per call, so a host can build it whenever it likes.
    """
    # Applied once to the whole router rather than copy-pasted per route.
    # verify_abdm_callback checks the Keycloak JWT signature against ABDM's
    # live JWKS plus iss/exp/aud/azp; it runs BEFORE the handler body, so
    # an unverified request never reaches dispatch() and gets a real 401.
    router = APIRouter(dependencies=[Depends(verify_abdm_callback)])

    for path, callback_type in CALLBACK_ROUTES:
        router.add_api_route(
            path,
            _make_handler(callback_type, settings),
            methods=["POST"],
            name=f"phr_callback_{callback_type}",
            summary=f"ABDM callback: {callback_type}",
        )

    return router
