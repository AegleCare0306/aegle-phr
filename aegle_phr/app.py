"""
Standalone FastAPI application -- a thin wrapper around build_router().

FOR SOLO DEVELOPMENT ONLY. The real deployment target is the PHR router
mounted into the existing ABDM backend's process (one client ID, one
callback URL, one ngrok host). Everything of substance lives in
build_router() and bootstrap(); this module must stay thin enough that
running standalone and running mounted cannot drift apart.

If you find yourself adding behaviour here, it belongs in api.py or
bootstrap.py instead -- otherwise it will exist standalone and silently
not exist when mounted.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aegle_phr.api import build_router
from aegle_phr.bootstrap import bootstrap
from aegle_phr.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Builds the standalone application: bootstrap, CORS, router.

    Args:
        settings: Defaults to the process-wide cached Settings loaded from
            this repo's .env.
    """
    if settings is None:
        settings = get_settings()

    bootstrap(settings)

    app = FastAPI(
        title="Aegle PHR",
        description=(
            "Patient-facing ABDM PHR app. Standalone dev server; in "
            "production this router is mounted into the ABDM backend."
        ),
        version="0.1.0",
    )

    # CORS is applied HERE and not in build_router() on purpose: middleware
    # is an application-level concern. A host application mounting the PHR
    # router owns its own CORS policy and must not have the PHR's silently
    # applied to every one of its routes.
    # Wildcard origin, deliberately: this is a sandbox test harness, the
    # X-Aegle-Key header is the access control, and "*" means Vercel preview
    # deployments work without editing .env. Narrow this before anything real.
    # allow_credentials must be False for "*" to be legal.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_router(settings))

    return app
