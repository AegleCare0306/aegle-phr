"""
Gateway bridge administration for the standalone Health Locker.

Two things need doing whenever the locker's deployment changes, and both
are easy to get dangerously wrong by hand:

  1. POINT THE BRIDGE AT THE RIGHT CALLBACK URL. Every ngrok restart on a
     non-reserved domain changes it, and ABDM silently keeps delivering
     callbacks to the old one until it is updated.

  2. GIVE A FACILITY THE RIGHT SERVICE ROLES. A facility registered only
     as HIP/HIU cannot act as a Health Locker: Setup Locker (8.3.18) and
     every subscription the locker raises will be rejected, and the
     rejection does not say "you are not a HEALTH_LOCKER".

WHY THIS EXISTS RATHER THAN THE M2 CLI. tools/m2_test_suite's own
bridge_gateway.py does (1) already -- but it builds its gateway token from
repo/server/config.py's CLIENT_ID, which is the EMR bridge. Running it to
"update the callback URL" while thinking about the locker silently
repoints the EMR's bridge instead, breaking every callback on port 8000.
This tool reads an explicit env file (default .env.locker) and acts only
on the bridge those credentials belong to, so the bridge it touches is
never ambiguous.

WHY IT DOES NOT USE facility.py::register_bridge_service(). That hits a
different ABDM domain entirely (the Health Facility Registry's
MutipleHRPAddUpdateServices) and only ADDS an association -- confirmed
live 2026-09-23, it rejects an existing one with ABDM-2500 rather than
updating its roles, so it cannot promote an existing HIP/HIU facility to
HEALTH_LOCKER. The Gateway's own PUT /bridge-service can.

ROLE CHANGES ARE READ-MODIFY-WRITE. The PUT replaces the whole record, so
--set-roles first GETs the current one and preserves every field it is not
explicitly changing. Building the payload from scratch would silently drop
whatever is already there.

Usage:
    python tools/bridge_service.py                       # show current state
    python tools/bridge_service.py --add-roles health_locker,phr --apply
    python tools/bridge_service.py --set-url https://xyz.ngrok-free.dev --apply
    python tools/bridge_service.py --env-file .env       # act on the EMR bridge instead

Nothing here ever prints the client secret or the gateway token.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from abdm_core.config import GatewayConfig, configure
from abdm_core.http import generate_request_id, generate_timestamp
from abdm_core.paths import StoragePaths, configure_paths
from abdm_core.session import get_gateway_token

from aegle_phr.settings import load_settings

TIMEOUT_SECONDS = 30

# The four role flags the Gateway's bridge-service record carries, mapped
# from the friendly names this tool accepts on the command line.
ROLE_FLAGS = {
    "hip": "isHip",
    "hiu": "isHiu",
    "health_locker": "isHealthLocker",
    "phr": "isPhr",
}


def build_headers(settings) -> dict[str, str]:
    """
    REQUEST-ID/TIMESTAMP/X-CM-ID plus the gateway token -- the envelope
    every Gateway-domain call takes. A fresh REQUEST-ID per call, so two
    calls are never conflated in ABDM's own logs.
    """
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": settings.abdm_x_cm_id,
        "Authorization": f"Bearer {get_gateway_token()}",
    }


def gateway_base(settings) -> str:
    return settings.abdm_gateway_base_url.rstrip("/")


def show_bridge(settings) -> dict | None:
    """
    GET /bridge-services -- the bridge and every service on it. ABDM
    resolves which bridge from the token itself; there is no id to pass.
    """
    response = requests.get(
        f"{gateway_base(settings)}/bridge-services",
        headers=build_headers(settings),
        timeout=TIMEOUT_SECONDS,
    )
    print(f"GET /bridge-services -> {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        print("  body:", response.text[:400])
        return None

    bridge = body.get("bridge") or {}
    print(f"  bridge : {bridge.get('id')!r}  {bridge.get('name')!r}")
    print(f"  url    : {bridge.get('url')!r}")
    print(f"  active : {bridge.get('active')}")
    services = body.get("services") or []
    print(f"  services ({len(services)}):")
    for service in services:
        print(
            f"    - {service.get('id')!r}  {service.get('name')!r}  "
            f"types={service.get('types')}  active={service.get('active')}"
        )
    return body


def get_service(settings, service_id: str) -> dict | None:
    """GET /bridge-service/serviceId/<id> -- one service's full record."""
    response = requests.get(
        f"{gateway_base(settings)}/bridge-service/serviceId/{service_id}",
        headers=build_headers(settings),
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        print(f"GET /bridge-service/serviceId/{service_id} -> {response.status_code}")
        print("  body:", response.text[:400])
        return None
    try:
        record = response.json()
    except ValueError:
        print("  body was not JSON:", response.text[:400])
        return None

    # Returned bare in the sandbox, but this endpoint's response shape is
    # not documented anywhere we hold -- unwrap a likely envelope rather
    # than assuming the bare form.
    if isinstance(record, dict) and "serviceId" not in record:
        for key in ("service", "data", "bridgeService"):
            if isinstance(record.get(key), dict):
                return record[key]
    return record if isinstance(record, dict) else None


def set_bridge_url(settings, url: str, apply: bool) -> None:
    """PATCH /bridge/url. Last write wins on ABDM's side, so it is safe to repeat."""
    print(f"PATCH /bridge/url  <- {url!r}")
    if not apply:
        print("  DRY RUN -- pass --apply to send it.")
        return
    response = requests.patch(
        f"{gateway_base(settings)}/bridge/url",
        json={"url": url},
        headers=build_headers(settings),
        timeout=TIMEOUT_SECONDS,
    )
    print(f"  -> {response.status_code} (202 expected, empty body)")
    if response.text.strip():
        print("     body:", response.text[:400])


def set_service_roles(settings, service_id: str, add_roles: list[str], apply: bool) -> None:
    """
    PUT /bridge-service with the named roles turned on, everything else
    left exactly as ABDM currently holds it.

    Roles are ADDED, never removed: this exists to promote a facility
    (HIP/HIU -> also HEALTH_LOCKER/PHR), and silently dropping a role a
    running integration depends on would be far worse than leaving a
    stale one set. Remove a role deliberately, by hand, if it is ever
    genuinely needed.
    """
    current = get_service(settings, service_id)
    if current is None:
        print(f"  no existing service record for {service_id!r} on this bridge -- refusing to guess one.")
        return

    print("  current record:")
    print("   ", json.dumps(current, indent=2).replace("\n", "\n    "))

    payload = {
        "bridgeId": settings.abdm_client_id,
        "serviceId": service_id,
        "name": current.get("name"),
        "isHip": bool(current.get("isHip")),
        "isHiu": bool(current.get("isHiu")),
        "isHealthLocker": bool(current.get("isHealthLocker")),
        "isPhr": bool(current.get("isPhr")),
        "endpoints": current.get("endpoints") or {},
        "attributes": current.get("attributes"),
        "active": bool(current.get("active", True)),
    }
    for role in add_roles:
        payload[ROLE_FLAGS[role]] = True

    print("  PUT /bridge-service payload:")
    print("   ", json.dumps(payload, indent=2).replace("\n", "\n    "))

    if not apply:
        print("  DRY RUN -- pass --apply to send it.")
        return

    response = requests.put(
        f"{gateway_base(settings)}/bridge-service",
        json=payload,
        headers=build_headers(settings),
        timeout=TIMEOUT_SECONDS,
    )
    print(f"  -> {response.status_code}")
    try:
        print("     body:", json.dumps(response.json(), indent=2)[:1200])
    except ValueError:
        print("     body:", (response.text or "(empty)")[:600])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--env-file",
        default=".env.locker",
        help="Which config to act on, relative to the aegle-phr root. Determines WHICH BRIDGE is touched. Default: .env.locker",
    )
    parser.add_argument("--service-id", help="Service/facility id. Default: ABDM_HEALTH_LOCKER_ID from the env file.")
    parser.add_argument(
        "--add-roles",
        help=f"Comma-separated roles to turn on: {', '.join(ROLE_FLAGS)}",
    )
    parser.add_argument("--set-url", help="Set the bridge callback URL. Default: ABDM_CALLBACK_URL from the env file.")
    parser.add_argument("--apply", action="store_true", help="Actually send the state-changing calls. Without it, everything is a dry run.")
    args = parser.parse_args()

    env_path = _PACKAGE_ROOT / args.env_file
    if not env_path.exists():
        parser.error(f"env file not found: {env_path}")

    settings = load_settings(env_path)

    # abdm_core refuses to log or capture until told where to write.
    configure_paths(StoragePaths(log_dir=settings.log_dir, storage_root=settings.storage_root))
    configure(GatewayConfig(
        client_id=settings.abdm_client_id,
        client_secret=settings.abdm_client_secret,
        gateway_base_url=settings.abdm_gateway_base_url,
        x_cm_id=settings.abdm_x_cm_id,
        extra_allowed_azp=frozenset(settings.abdm_extra_allowed_azp),
    ))

    service_id = args.service_id or settings.abdm_health_locker_id

    print(f"config  : {env_path}")
    print(f"bridge  : {settings.abdm_client_id}")
    print(f"service : {service_id or '(none set)'}")
    print(f"mode    : {'APPLY' if args.apply else 'DRY RUN'}")
    print("=" * 72)

    show_bridge(settings)

    # service-details-by-service-id. Shown on every run when there is a
    # service to show: the bridge listing gives a `types` summary, this
    # gives the actual record those types are derived from -- which is
    # what you need when a role change did or did not take effect.
    if service_id and not args.add_roles:
        print()
        print("=" * 72)
        print(f"GET /bridge-service/serviceId/{service_id}")
        print("=" * 72)
        record = get_service(settings, service_id)
        if record is not None:
            print(json.dumps(record, indent=2))

    if args.set_url:
        print()
        print("=" * 72)
        set_bridge_url(settings, args.set_url, args.apply)

    if args.add_roles:
        roles = [r.strip().lower() for r in args.add_roles.split(",") if r.strip()]
        unknown = [r for r in roles if r not in ROLE_FLAGS]
        if unknown:
            parser.error(f"unknown role(s) {unknown}; known roles are {sorted(ROLE_FLAGS)}")
        if not service_id:
            parser.error("no service id -- pass --service-id or set ABDM_HEALTH_LOCKER_ID in the env file")
        print()
        print("=" * 72)
        print(f"Adding roles {roles} to service {service_id}")
        set_service_roles(settings, service_id, roles, args.apply)

    if args.apply and (args.set_url or args.add_roles):
        print()
        print("=" * 72)
        print("AFTER")
        print("=" * 72)
        show_bridge(settings)


if __name__ == "__main__":
    main()
