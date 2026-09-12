"""
Provider Directory -- all-providers / provider-by-id / govt-programs
(spec SS10.3.13-15, "User Initiated Linking" section). The simplest module
in this project so far: three stateless, read-only GETs, no patient
session token, no encryption, and no spec-vs-Postman disagreement -- both
sources agree on URL, headers, and response shape for all three.

NOT part of User Initiated Linking itself (discovering/linking NEW care
contexts, spec section 10's own later sub-sections) -- that's explicitly
the LAST chunk in this project. This module is just the read-only
directory lookup UIL would eventually use to let a patient find a HIP to
link against; nothing here performs any linking.

HOST -- A THIRD, MORE SPECIFIC BASE URL, DIFFERENT FROM BOTH OTHER HIE-CM
MODULES: settings.abdm_gateway_base_url
(https://dev.abdm.gov.in/api/hiecm/gateway/v3 in .env), NOT
abdm_hiecm_base_url (https://dev.abdm.gov.in/api/hiecm, no /gateway/v3)
that links.py/consent.py use. Confirmed against both the spec's own base
path for SS10.3.13-15 and Postman's saved requests for all three -- they
agree with each other on this, unlike Links' SS6.12-vs-SS9.3.5 mess.

HEADERS -- GENUINELY DIFFERENT FROM LINKS/CONSENT, CONFIRMED IN BOTH
PLACES: only REQUEST-ID + TIMESTAMP + X-CM-ID are listed as required in
the spec's own header table for all three endpoints -- notably NOT
X-AUTH-TOKEN (these are global directory lookups, not tied to a patient
session -- there is no session-token parameter to any of these three
functions at all, unlike every other module in aegle_phr/phr/). Postman's
saved requests each carry a collection-level `bearer` auth block, but
that's Postman's own default applied uniformly across the whole
collection, not proof the live API enforces it for THESE three --
Postman's own visible per-request header list, like the spec, does not
list Authorization either. `_headers()` below still sends
`Authorization: Bearer {get_gateway_token()}` anyway, matching the safe-
default convention this project uses everywhere the spec is ambiguous
(costs nothing if unneeded) -- but does NOT send X-AUTH-TOKEN, because
there is no token to send. IF A LIVE CALL 401s/403s, THE FIRST THING TO
CHECK IS WHETHER Authorization NEEDS TO BE DROPPED, not added to.

NO ENCRYPTION: plain GETs, no request body -- same HIE-CM-family
exemption as links.py/consent.py, see CERTIFICATES.md.

QUERY PARAMS (all-providers, SS10.3.13): the spec's own example uses
`stateCode=-1&districtCode=-1&name=test` -- `-1` reads as "any"/
unfiltered for the code params. There is no ABDM state/district code
lookup table anywhere in this project, so search_providers() only takes
a free-text `name` and always sends stateCode=-1/districtCode=-1 --
deliberately no state/district picker, there is nothing to source one
from.

RESPONSE SHAPES -- CONFIRMED AGAINST BOTH THE SPEC AND POSTMAN, NO SAVED
LIVE EXAMPLE YET: all-providers and govt-programs are each a bare ARRAY
of provider objects; provider-by-id is a single object (not wrapped, not
an array). All three return ABDM's raw response body untouched -- the
Pydantic models below are documentation-only CONTRACTS, never used to
gate or validate the actual response, same reasoning as every other
module in this project (an unexpected live shape should never cause a
misparse, only a documented gap). Provider-by-id's own doc example is a
strict subset of all-providers' per-item shape (missing isGovtEntity/
endpoints) -- likely just a documentation shortcut, not a guarantee
those fields are absent live.

RETRY: default classifier. Read-only, side-effect-free, safe to retry
freely -- same as links.py.
"""

import time
from typing import Any

import requests
from pydantic import BaseModel

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30


class ProviderIdentifier(BaseModel):
    name: str | None = None
    id: str | None = None


class ProviderEndpoint(BaseModel):
    use: str | None = None
    connectionType: str | None = None
    address: str | None = None


class ProviderEndpoints(BaseModel):
    """Often just `{}` in the documented examples -- optional/display-if-present, not a guaranteed shape."""

    healthLockerEndpoints: list[ProviderEndpoint] = []


class Provider(BaseModel):
    """
    Shared per-provider contract for all three endpoints -- documentation
    only, see module banner. Provider-by-id's own doc example omits
    isGovtEntity/endpoints, which is why both stay optional here rather
    than required.
    """

    identifier: ProviderIdentifier | None = None
    facilityType: list[str] = []
    isHIP: bool | None = None
    isGovtEntity: bool | None = None
    endpoints: ProviderEndpoints | None = None


def _headers(x_cm_id: str) -> dict[str, str]:
    """
    REQUEST-ID + TIMESTAMP + X-CM-ID + Authorization -- deliberately NO
    X-AUTH-TOKEN, unlike links.py/consent.py's identical-looking
    `_headers()` -- see module banner's HEADERS section for why these
    three calls carry no patient session token at all.
    """
    return {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-CM-ID": x_cm_id,
    }


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _get(settings: Settings, route: str, description: str, path: str, params: dict[str, Any] | None) -> AbdmResult:
    """Shared GET/log/archive plumbing for all three functions below -- mirrors links.py's own single-call shape, just parametrized since there are three near-identical calls here instead of one."""
    url = f"{settings.abdm_gateway_base_url.rstrip('/')}{path}"
    headers = _headers(settings.abdm_x_cm_id)

    log_phase(description)
    started = time.monotonic()

    try:
        response = call_with_retry(
            lambda: requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS),
            description=description,
        )
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, params, None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call(description, url, response.status_code)
    archive(route, url, params, response.status_code, body, duration_ms, None, ())

    return AbdmResult(status_code=response.status_code, body=body)


def search_providers(settings: Settings, name: str, state_code: int = -1, district_code: int = -1) -> AbdmResult:
    """GET {abdm_gateway_base_url}/providers?stateCode={state_code}&districtCode={district_code}&name={name} -- see module banner for why state/district always send -1 (no lookup table exists to source real codes from)."""
    params = {"stateCode": state_code, "districtCode": district_code, "name": name}
    return _get(settings, "/phr/providers/search", "PHR search providers", "/providers", params)


def get_provider(settings: Settings, provider_id: str) -> AbdmResult:
    """GET {abdm_gateway_base_url}/providers/{provider_id} -- single provider detail, not wrapped/not an array."""
    return _get(settings, "/phr/providers/get-one", "PHR get provider by id", f"/providers/{provider_id}", None)


def get_govt_programs(settings: Settings) -> AbdmResult:
    """GET {abdm_gateway_base_url}/govt-programs -- no query params. Filed under Postman's "Gateway" folder as "all-govt-programs", not "User Initiated Linking" where the other two live -- same headers/base URL, just filed differently in the collection."""
    return _get(settings, "/phr/providers/govt-programs", "PHR get govt programs", "/govt-programs", None)
