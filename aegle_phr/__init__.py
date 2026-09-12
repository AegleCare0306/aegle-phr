"""
aegle-phr -- the patient-facing (PHR) side of Aegle's ABDM integration.

Deliberately empty of re-exports. Importing this package must not pull in
FastAPI, SQLAlchemy, or configuration -- it is designed to be mounted into
another application's process, where an import-time side effect would fire
inside the host's import graph. Import what you need directly:

    from aegle_phr.bootstrap import bootstrap
    from aegle_phr.api import build_router
    from aegle_phr.settings import load_settings
"""

__version__ = "0.1.0"
