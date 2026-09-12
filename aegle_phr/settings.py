"""
Configuration for the PHR app, loaded from .env via pydantic-settings.

NOTHING IS INSTANTIATED AT IMPORT. Importing this module must not read a
file, resolve a path, or touch the environment -- see the module docstring
in aegle_phr/bootstrap.py for why that rule exists (this package is
designed to be mounted into the existing ABDM backend's process, where an
import-time side effect would fire during the host's own import graph,
before the host has decided anything).

Call load_settings() (or the cached get_settings()) explicitly instead.

WHY .env AND NOT A config.py: the existing backend hardcodes CLIENT_ID and
CLIENT_SECRET in server/config.py, and a real sandbox secret is already in
that repo's git history as a result. This repo does not repeat that -- the
secret lives only in .env, which .gitignore excludes.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = the directory containing this package. Used only to resolve
# relative paths from .env; computed inside functions, never at import.
_PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """
    Every value comes from the environment or .env. Field names map to
    upper-case env vars (abdm_client_id <- ABDM_CLIENT_ID).
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- ABDM gateway (shared with the existing backend) ----------------
    abdm_client_id: str
    abdm_client_secret: str
    abdm_gateway_base_url: str
    abdm_abha_base_url: str
    abdm_hiecm_base_url: str
    # P11 -- Consent Auto-Approval (create-pin / verify-pin / auto-approve)
    # lives under a FOURTH, distinct host -- confirmed via a live-captured
    # Postman example (ABDM Collection -> Building PHR App -> Setup
    # Subscriptions/Setup Auto-approval), not the spec PDF, which documents
    # a different endpoint under abdm_hiecm_base_url that turned out not to
    # match a real capture at all. See aegle_phr/phr/consent.py's own
    # module banner for the full story. Defaulted (unlike its three
    # siblings above, which are required) since this sandbox's own value
    # is stable/well-known and every environment mounting this app should
    # not need to discover and set a fourth ABDM host just to pick up this
    # one pass's fix.
    abdm_cm_base_url: str = "https://dev.abdm.gov.in/cm"
    abdm_x_cm_id: str = "sbx"
    abdm_callback_url: str

    # --- PHR-specific ---------------------------------------------------
    # FULL certificate URL, deliberately not assembled inside abdm_core:
    # get_public_certificate() takes the whole URL precisely so the PHR and
    # the HIP/HIU backend can use different endpoints in one process
    # without one serving the other's key. Defaults to the PHR endpoint
    # (see the validator below) if not set explicitly.
    phr_certificate_url: str = ""

    # PROFILE certificate URL (P1-F) -- deliberately DIFFERENT from
    # phr_certificate_url above. Real Aadhaar-based ABHA enrollment
    # (aegle_phr/phr/aadhaar_enrollment.py) is ported from repo/server/
    # abha.py, whose encrypt() (via repo/tools/m1_test_suite/common.py)
    # calls get_public_certificate() with NO url override -- which
    # defaults to {ABHA_BASE_URL}/profile/public/certificate, a 4096-bit
    # key, not the 2048-bit key phr_certificate_url points at. Using the
    # wrong one produces ciphertext ABDM cannot decrypt, silently. Same
    # derived-default pattern as phr_certificate_url -- see the validator
    # below.
    abdm_profile_certificate_url: str = ""

    # Shared access key for the app API (NOT the ABDM callback surface --
    # see aegle_phr/access.py). Empty means the app API is unusable, which
    # is the intended fail-closed behaviour rather than an open door.
    phr_api_access_key: str = ""

    # The PHR's HIU identifier, sent as the X-HIU-ID header (P15 -- User-
    # Initiated Linking is the first thing that actually sends it, see
    # aegle_phr/phr/uil.py). Set to CLIENT_ID in .env -- this project's own
    # established self-service pattern, independently confirmed for three
    # other endpoint families before this one (Data Flow self-view fetch,
    # Subscription Flow self-subscription, Consent Auto-Approval's own
    # hiu.id correction). Still worth a live confirmation check before any
    # NEW endpoint family's first real call -- see .env.example's comment.
    abdm_hiu_id: str = ""

    # --- Infrastructure --------------------------------------------------
    database_url: str
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    storage_root: Path = Path("storage")
    log_dir: Path = Path("logs")

    @model_validator(mode="after")
    def _derive_and_resolve(self):
        # Derive the PHR certificate URL from the ABHA base URL unless the
        # environment set one explicitly.
        if not self.phr_certificate_url:
            base = self.abdm_abha_base_url.rstrip("/")
            object.__setattr__(
                self, "phr_certificate_url", f"{base}/phr/app/login/public/certificate"
            )

        if not self.abdm_profile_certificate_url:
            base = self.abdm_abha_base_url.rstrip("/")
            object.__setattr__(
                self, "abdm_profile_certificate_url", f"{base}/profile/public/certificate"
            )

        # Relative storage/log paths are resolved against this repo's root,
        # not the process's cwd -- a mounted PHR inherits the HOST's cwd,
        # which is not this repo. (The existing backend hit this exact
        # class of bug; see its api_capture.py "ANCHOR FIX" comment.)
        repo_root = _PACKAGE_DIR.parent
        for field in ("storage_root", "log_dir"):
            value = getattr(self, field)
            if not value.is_absolute():
                object.__setattr__(self, field, (repo_root / value).resolve())

        return self


def default_env_file() -> Path:
    """Path to this repo's .env. Resolved on call, never at import."""
    return _PACKAGE_DIR.parent / ".env"


def load_settings(env_file: Path | str | None = None) -> Settings:
    """
    Builds a Settings instance.

    Args:
        env_file: .env to read. Defaults to this repo's own .env. Pass a
            different path (or a non-existent one, to rely purely on real
            environment variables) when mounting into a host application
            that manages its own configuration.
    """
    if env_file is None:
        env_file = default_env_file()
    return Settings(_env_file=env_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Process-wide cached Settings, for the standalone server and for CLI
    entry points (alembic). A host application mounting this package
    should build its own Settings and pass it in explicitly rather than
    relying on this cache.
    """
    return load_settings()
