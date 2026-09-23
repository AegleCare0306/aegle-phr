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

import os
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

    # The service id of OUR OWN Health Locker -- the Aegle Urgent Care
    # facility, registered with ABDM as HEALTH_LOCKER + PHR on top of the
    # HIP + HIU roles it already had. CONFIRMED LIVE 2026-09-22 against
    # GET /api/hiecm/gateway/v3/bridge-services, under bridge SBXID_046112
    # (the same CLIENT_ID everything else in this project uses -- NOT the
    # unused SBXID_073333): {"id": "IN2410002590", "name": "Aegle Urgent
    # Care", "types": ["HIP","HIU","HEALTH_LOCKER","PHR"], "active": true}.
    #
    # This one value is both the X-LOCKER-ID header on Setup Locker
    # (8.3.18) and the hiu.id of every subscription and consent the locker
    # raises. P19 replaced the old self-view / self-subscription
    # workarounds, which used CLIENT_ID as a stand-in HIU id, with this.
    #
    # NOTE it is ALSO one of the four HIPs in repo/server/config.py's own
    # HIPS list, so the same facility plays both sides: a hospital that
    # holds records, and the locker that collects them. Deliberate, not a
    # misconfiguration -- see CC_PROMPT_P19's own section 1.
    abdm_health_locker_id: str = ""

    # Extra `azp` claim values accepted on INBOUND ABDM callbacks, on top
    # of the always-allowed {"gateway", ABDM_CLIENT_ID}. A JSON array in
    # .env (same convention as CORS_ORIGINS); empty by default.
    #
    # WHY THIS EXISTS: confirmed live 2026-09-22 -- ABDM's Health Locker
    # callbacks (Setup Locker's own subscription on-init and the GRANTED
    # hiu/notify, and by extension the 8.3.11 LINK/DATA alerts the whole
    # locker automation depends on) arrive correctly signed by ABDM's
    # Keycloak but carrying azp="TEST_PHR" -- a third service account
    # beyond "gateway" and our own client id. Without it here every one
    # of them is rejected 401 and the automation never runs.
    #
    # Configuration rather than a literal in abdm_core because "TEST_PHR"
    # is a SANDBOX service account name and that library is shared with
    # production. Safe by construction: signature/iss/exp are verified
    # against ABDM's live JWKS before azp is looked at (see
    # abdm_core/callback_auth.py).
    abdm_extra_allowed_azp: list[str] = Field(default_factory=list)

    # Whether THIS process owns the five HIU callback paths (section 6
    # consent on-init/notify/on-fetch, section 7 on-request, and the HIP's
    # direct data push). See aegle_phr/callbacks/router.py's own banner.
    #
    # FALSE BY DEFAULT because of a real constraint, not caution: when
    # aegle_phr is mounted INSIDE repo/server/main.py, both apps share one
    # FastAPI instance, one client id and one callback URL -- and two
    # routers cannot both own a path. Whichever is included first wins,
    # silently. In that deployment repo/'s own M3 HIU code owns them, and
    # this must stay false or the consent chain half-breaks in a way that
    # looks like nothing happened.
    #
    # TRUE is the standalone deployment P20 exists for: the locker running
    # as its own registered ABDM entity, with its own client id, its own
    # callback URL and its own port, where nothing competes for those
    # paths and the locker must handle its own consent and data flow to
    # function at all.
    abdm_locker_owns_hiu_callbacks: bool = False

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
    """
    Path to this repo's .env. Resolved on call, never at import.

    P20 -- AEGLE_PHR_ENV_FILE overrides it. The standalone locker and the
    mounted deployment need genuinely DIFFERENT configuration (different
    client id, different callback URL, and opposite values of
    abdm_locker_owns_hiu_callbacks), and they both read this package's
    settings. One file cannot hold both: setting the standalone's values
    in .env would silently reconfigure the mounted backend on port 8000.
    """
    override = os.environ.get("AEGLE_PHR_ENV_FILE")
    if override:
        return Path(override)
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
