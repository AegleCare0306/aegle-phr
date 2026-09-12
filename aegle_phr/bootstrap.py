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
        ))

        configure_paths(StoragePaths(
            log_dir=settings.log_dir,
            storage_root=settings.storage_root,
        ))

        init_engine(settings.database_url)

        # P17 -- aegle_phr/phr/data_flow.py calls straight into three of
        # repo/'s own repository modules (hiu_consent_repository,
        # hiu_health_information_repository,
        # pending_health_information_request_repository), not just files
        # under server/ -- fine in the real mounted deployment (same
        # process, repo/'s own engine already initialised by
        # repo/server/main.py's own startup, P16) but this package ALSO
        # ships its own standalone dev server (aegle_phr/app.py, "FOR
        # SOLO DEVELOPMENT ONLY"), whose bootstrap path never touched
        # repo/'s engine at all -- data_flow.py's own error message
        # already documents this combination isn't really supported, but
        # the failure should be an explicit, early one, not whatever
        # RuntimeError shape server/db.py's get_engine() raises the first
        # time some standalone-mode request happens to reach it. Wrapped
        # in try/except ImportError like every other place aegle_phr
        # reaches into repo/'s package -- this package must still start
        # up fine on a machine that doesn't have repo/'s server package
        # installed at all. init_engine() is idempotent (P16) -- safe
        # even though the mounted deployment calls it separately too;
        # the two code paths never run in the same process.
        try:
            from server.config import DATABASE_URL as _repo_database_url
            from server.db import init_engine as _repo_init_engine

            _repo_init_engine(_repo_database_url)
        except ImportError:
            pass  # repo/'s server package isn't installed/importable -- standalone mode's
                  # own per-call try/except ImportError blocks already handle this cleanly.

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
