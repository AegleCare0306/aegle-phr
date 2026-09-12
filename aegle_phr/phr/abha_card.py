"""
PHR-side wrapper around abdm_core.profile_resources.get_abha_card() (P1-L)
-- ABHA card fetch for the "ABHA number already exists" branch of Aadhaar
registration (see testui's AadhaarRegisterScreen.tsx). Confirmed live
(Aayush, 2026-08-31): enrol/byAadhaar's own session token (tokens.token)
works as the X-token here, the same one already used for email linking --
see aegle_phr/phr/email_verification.py's own banner for the fuller story
on that token being transaction-scoped yet accepted by some endpoints.

BASE64, NOT RAW BYTES -- this app's entire API surface is JSON in/out (the
Console panel renders every response as JSON), so the binary card is
base64-encoded into the response body alongside its Content-Type, rather
than returned as a raw byte stream. The frontend decodes it into a data:
URI to display. Content-Type is passed through uninterpreted rather than
hardcoded here -- confirmed live 2026-08-31 it's an image (see
abdm_core.profile_resources' own banner) -- so the frontend still reads
the real value rather than this layer assuming a fixed one.

NOT SELF-ARCHIVING'S ONE EXCEPTION HERE: unlike every other PHR wrapper in
this project, the archived response_body is the base64 payload, not
ABDM's raw bytes (redact() only understands JSON-shaped values) -- still
routed through the same archive()/redact() call as everything else, no
new mechanism.
"""

import base64
import time
from dataclasses import dataclass
from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase
from abdm_core.profile_resources import get_abha_card as _abdm_get_abha_card

from aegle_phr.phr.call_log import archive
from aegle_phr.settings import Settings


@dataclass(frozen=True)
class AbhaCardResult:
    status_code: int | None
    content_type: str | None
    base64_body: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


def get_abha_card(settings: Settings, x_token: str) -> AbhaCardResult:
    """Read-only GET, no plaintext secrets in this call at all (x_token isn't a user-supplied secret the way an OTP/password/mobile is, so nothing is passed to plaintext_secrets)."""
    log_phase("Fetching ABHA card")
    route = "/phr/aadhaar-enrollment/abha-card"
    url = f"{settings.abdm_abha_base_url.rstrip('/')}/profile/account/abha-card"
    started = time.monotonic()

    try:
        response = _abdm_get_abha_card(settings.abdm_abha_base_url, x_token)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"ABHA card fetch failed: {exc}")
        archive(route, url, {}, None, None, duration_ms, str(exc), ())
        return AbhaCardResult(status_code=None, content_type=None, base64_body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    succeeded = 200 <= response.status_code < 300
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip() or None
    body_b64 = base64.b64encode(response.content).decode("ascii") if succeeded else None
    archived_body: Any = {"contentType": content_type, "base64Length": len(body_b64)} if body_b64 else response.text
    archive(route, url, {}, response.status_code, archived_body, duration_ms, None, ())
    return AbhaCardResult(status_code=response.status_code, content_type=content_type, base64_body=body_b64)
