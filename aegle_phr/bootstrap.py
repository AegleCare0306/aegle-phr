"""
The single place where this package does anything with a side effect.

WHY EVERY OTHER MODULE IS INERT AT IMPORT: this package is built to be
mounted into the existing ABDM backend's process, not just to run its own
server. A host application does:

    from aegle_phr.bootstrap import bootstrap
    from aegle_phr.api import build_router

    bootstrap(settings)
    app.include_router(build_router(settings))

If importing aegle_phr.api created an engine, read a .env, resolved a
storage path, or called abdm_core.configure(), all of that would fire
during the HOST's import graph -- before the host has loaded its own
configuration, and potentially clobbering the host's abdm_core setup with
the PHR's. So: no module-level side effects anywhere in aegle_phr, and
everything that must happen once happens here.

IDEMPOTENT ON PURPOSE. The host may have bootstrapped already; a second
call must not create a second engine (and therefore a second connection
pool), and must not re-point abdm_core at different credentials.
"""

import socket
import threading

import urllib3.util.connection as _urllib3_connection

from abdm_core.config import GatewayConfig, configure
from abdm_core.observability.flow_logger import log_error, log_phase
from abdm_core.paths import StoragePaths, configure_paths

from aegle_phr.db import init_engine, reset_engine
from aegle_phr.settings import Settings

_bootstrapped = False
_bootstrap_lock = threading.Lock()


def _force_ipv4_for_outbound_requests() -> None:
    """
    P12 addendum (2026-09-03) -- CONFIRMED LIVE, not speculative: mobile
    OTP login hung indefinitely (past its own 30s timeout, never logging
    success OR failure) because outbound `requests` calls from this
    process were resolving abhasbx.abdm.gov.in to an IPv6 address whose
    current route from this network is dead -- OS-level diagnosis (Get-
    NetTCPConnection showed the socket sitting in SynSent; Test-NetConnection
    confirmed TcpTestSucceeded:True over IPv4 to the exact same server,
    False over IPv6 to the exact same address) -- ABDM's own server is
    reachable fine, only the IPv6 PATH from this specific network is
    broken right now. requests/urllib3 has no "happy eyeballs" fallback
    (unlike a browser) -- once it picks the IPv6 address from DNS, it
    just hangs on that one connection attempt, and Windows' own SYN retry
    behavior can keep that hang going well past the request's own
    `timeout=`. Every OTHER ABDM host used in this project (confirmed via
    nslookup) ALSO has an IPv6 record, so this was never guaranteed to
    stay isolated to the login host specifically -- it happened to be
    login's IPv6 path that was down at that moment, not a defect unique
    to that one call.

    Forcing IPv4-only DNS resolution, process-wide, via urllib3's own
    documented allowed_gai_family() hook -- the standard, minimal fix for
    exactly this class of problem, NOT a broader networking change (IPv4
    to every ABDM host used here was independently confirmed working).
    Runs once, inside bootstrap()'s own idempotent guard, before any real
    outbound call is made -- affects every `requests.*` call in this
    process (aegle_phr's own, and repo/'s, since both share one process
    once mounted), not just this module's own call sites, since urllib3
    is one shared library instance per process regardless of which module
    imports it.
    """
    def _allowed_gai_family():
        return socket.AF_INET

    _urllib3_connection.allowed_gai_family = _allowed_gai_family


def bootstrap(settings: Settings) -> None:
    """
    Configures abdm_core and creates the database engine. Safe to call
    more than once; every call after the first is a no-op.

    Deliberately does NOT create the log/storage directories. abdm_core
    creates them lazily at write time, so a PHR that never logs never
    leaves empty directories behind, and nothing here touches the
    filesystem at bootstrap.

    Deliberately does NOT run migrations. Schema changes are an explicit
    `alembic upgrade head`, never something a process does to itself on
    startup.
    """
    global _bootstrapped

    # Double-checked locking: two workers starting concurrently must not
    # both build an engine. init_engine() is itself idempotent, so this is
    # belt-and-braces rather than the only guard.
    if _bootstrapped:
        return

    with _bootstrap_lock:
        if _bootstrapped:
            return

        _force_ipv4_for_outbound_requests()

        configure(GatewayConfig(
            client_id=settings.abdm_client_id,
            client_secret=settings.abdm_client_secret,
            gateway_base_url=settings.abdm_gateway_base_url,
            x_cm_id=settings.abdm_x_cm_id,
            extra_allowed_azp=frozenset(settings.abdm_extra_allowed_azp),
        ))

        configure_paths(StoragePaths(
            log_dir=settings.log_dir,
            storage_root=settings.storage_root,
        ))

        # P20 -- ONE engine, this app's own. The block that used to sit
        # here additionally initialised repo/'s engine, because
        # data_flow.py reached straight into three of repo/'s repository
        # modules and they needed a live engine of their own. Those reaches
        # are gone: consent artefacts, pending sessions and fetched record
        # content now live in this app's own locker_* tables (see
        # aegle_phr/phr/locker_hiu_repository.py), so there is no second
        # engine to initialise and no ImportError branch to guard.
        #
        # This is what makes standalone mode real rather than nominal. The
        # mounted deployment is unaffected: repo/server/main.py still
        # initialises its own engine at its own startup, exactly as before.
        init_engine(settings.database_url)

        # P20 -- re-trust the bridges of any data request still awaiting
        # its push. The trust set (see aegle_phr/phr/hip_trust.py) lives
        # in process memory, so without this a restart mid-transfer would
        # reject the HIP's push for a request we ourselves made moments
        # earlier. A pure DB read: startup must not depend on ABDM being
        # reachable, and must not fail if this table does not exist yet
        # (a host that has not run the migrations).
        try:
            from aegle_phr.phr import hip_trust
            from aegle_phr.phr import locker_hiu_repository

            warmed = hip_trust.warm_trusted_bridges(locker_hiu_repository.pending_hip_bridge_ids())
            if warmed:
                log_phase(f"Re-trusted {warmed} bridge(s) with data transfers still in flight")
        except Exception as exc:
            log_error(f"Could not re-trust in-flight bridges at startup: {type(exc).__name__}: {exc}")

        _bootstrapped = True


def is_bootstrapped() -> bool:
    """Whether bootstrap() has completed. Lets a host skip a redundant call."""
    return _bootstrapped


def reset_bootstrap() -> None:
    """
    Undoes bootstrap() far enough to run it again -- disposes the engine
    and clears the flag.

    For tests only. abdm_core's own configure()/configure_paths() are left
    as they are: they hold no resources, and clearing them would break a
    host application that configured them itself.
    """
    global _bootstrapped

    reset_engine()
    _bootstrapped = False
