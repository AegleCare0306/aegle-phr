"""
Shared-key gate for the app API.

Applied to the app-API router ONLY, never to the ABDM callback router:
ABDM has no way to send our key, so gating /api/v3/hiu/* would make every
callback fail -- and fail invisibly from our side, since the only symptom
is ABDM no longer receiving acks.
"""

import secrets

from fastapi import Header, HTTPException

from aegle_phr.settings import Settings


def api_key_dependency(settings: Settings):
    """Builds the dependency. Rejects everything when no key is configured."""
    expected = settings.phr_api_access_key

    def check(x_aegle_key: str = Header(default="")) -> None:
        # .encode() because compare_digest raises TypeError on non-ASCII str.
        if not expected or not secrets.compare_digest(
            x_aegle_key.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="Invalid or missing X-Aegle-Key")

    return check
