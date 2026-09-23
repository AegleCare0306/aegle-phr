"""
Inbound ABDM callback routes owned by the PHR app.

=============================================================================
THE FIVE HIU PATHS, AND WHY THEY ARE CONDITIONAL
=============================================================================
Two routers in one FastAPI app cannot both own a path: whichever is
included first wins, silently, and the other's handler never runs. That
constraint has not gone away -- what changed in P20 is that there are now
two DEPLOYMENTS, and the right owner differs between them.

    /api/v3/hiu/consent/request/on-init
    /api/v3/hiu/consent/request/notify
    /api/v3/hiu/consent/on-fetch
    /api/v3/hiu/health-information/on-request
    /api/v3/hiu/health-information/push

MOUNTED (settings.abdm_locker_owns_hiu_callbacks = False, the default):
aegle_phr runs inside repo/server/main.py, sharing one client id and one
callback URL. repo/server/callbacks/router.py owns all five; this router
registers none of them, exactly as before P20.

STANDALONE (= True): the locker runs as its own registered ABDM entity --
own client id, own callback URL, own port -- and nothing else in the
process can own them. It MUST handle them itself; a PHR app that cannot
complete its own consent and data flow is not independent in any
meaningful sense, which was the whole point of P20.

Registering them unconditionally would silently half-break the mounted
deployment. Registering them never was what made the PHR app unable to
stand alone. This flag is the honest answer to a genuine fork, not a
feature toggle -- set it once per deployment and leave it.
=============================================================================

Every route below is a plain `def`, not `async def`. See aegle_phr/db.py
for why (blocking DB + blocking requests -> threadpool, not event loop).
"""

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Body, Depends, Request

from abdm_core.callback_auth import verify_abdm_callback
from abdm_core.http import generate_request_id
from abdm_core.observability.flow_logger import log_error, set_correlation_id

from aegle_phr.callbacks import hiu_services, subscription_services, uil_services
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
    # registered anywhere and does not collide with the five HIU paths below.
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
    "subscription_notify": lambda settings, payload, request_id_header: subscription_services.handle_subscription_notify(settings, payload, request_id_header),
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

# P20 -- the five HIU paths from this module's own banner, registered ONLY
# when settings.abdm_locker_owns_hiu_callbacks is true. Kept as data as
# well as prose so a test can assert they are absent in the mounted
# deployment and present in the standalone one.
#
# The push path is the odd one out: the HIP posts to it DIRECTLY, not
# through the gateway, because we supply it ourselves as dataPushUrl on
# the section 7 request. It is grouped here anyway -- same ownership
# question, same answer -- and still sits behind verify_abdm_callback,
# since the HIP's push is signed the same way.
HIU_CALLBACK_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/v3/hiu/consent/request/on-init", "consent_request_on_init"),
    ("/api/v3/hiu/consent/request/notify", "consent_request_notify"),
    ("/api/v3/hiu/consent/on-fetch", "consent_on_fetch"),
    ("/api/v3/hiu/health-information/on-request", "health_information_on_request"),
    ("/api/v3/hiu/health-information/push", "health_information_push"),
)

_HIU_HANDLERS: dict[str, Callable[[Settings, Any, str | None], None]] = {
    "consent_request_on_init": lambda settings, payload, request_id_header: hiu_services.handle_consent_request_on_init(settings, payload, request_id_header),
    "consent_request_notify": lambda settings, payload, request_id_header: hiu_services.handle_consent_request_notify(settings, payload, request_id_header),
    "consent_on_fetch": lambda settings, payload, request_id_header: hiu_services.handle_consent_on_fetch(settings, payload, request_id_header),
    "health_information_on_request": lambda settings, payload, request_id_header: hiu_services.handle_health_information_on_request(settings, payload, request_id_header),
    "health_information_push": lambda settings, payload, request_id_header: hiu_services.handle_health_information_push(settings, payload, request_id_header),
}

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
        # inside it. Separate dicts (one per feature area), checked in
        # turn -- callback_type namespaces don't overlap between them.
        real_handler = (
            _SUBSCRIPTION_HANDLERS.get(callback_type)
            or _UIL_HANDLERS.get(callback_type)
            or _HIU_HANDLERS.get(callback_type)
        )
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

    # P20 -- the five HIU paths only when this deployment owns them. See
    # this module's own banner for why this is a deployment fork rather
    # than an unconditional registration.
    routes = CALLBACK_ROUTES
    if settings.abdm_locker_owns_hiu_callbacks:
        routes = routes + HIU_CALLBACK_ROUTES

    for path, callback_type in routes:
        router.add_api_route(
            path,
            _make_handler(callback_type, settings),
            methods=["POST"],
            name=f"phr_callback_{callback_type}",
            summary=f"ABDM callback: {callback_type}",
        )

    return router
