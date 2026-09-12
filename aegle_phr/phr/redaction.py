"""
Keeping plaintext secrets out of the archive and the logs.

Plaintext mobile numbers, OTP values and passwords arrive at this backend
from the test UI (they have to -- the RSA encryption happens here, against
the PHR certificate). They must never reach abdm_call_log, the flow log, or
anything that gets pasted into a chat.

TWO INDEPENDENT LAYERS, on purpose. Either alone would be a single point of
failure for a leak that is invisible once it has happened:

  1. Key-based  -- any dict key that names a secret has its value replaced,
     wherever it appears in the structure.
  2. Value-based -- the specific plaintext strings handled during THIS call
     are scrubbed by exact match anywhere they appear, including places a
     key-based rule would not think to look (an ABDM error message that
     echoes the input back, for instance).

The RSA-encrypted forms are deliberately NOT redacted. They are opaque, they
are what actually went on the wire, and they are exactly what is needed to
diagnose a decrypt failure on ABDM's side.
"""

import re
from typing import Any

REDACTED = "«redacted»"
REDACTED_JWT = "«redacted-jwt»"

# Matched case-insensitively against dict keys, as substrings.
_SECRET_KEY_FRAGMENTS = (
    "password",
    "otpvalue",
    "mobile",
    "mobilenumber",
    "loginid",
    # BEARER TOKENS (added after the 2026-08-27 live run). /enrollment/verify
    # returns tokens.token -- an RS512 JWT whose base64 payload contains a
    # "mobile" claim IN CLEAR. The literal-string scrub below could never
    # catch it, because the number is base64-encoded inside the token, so the
    # archive ended up holding a recoverable mobile number despite passing
    # every redaction check. Note "txnId" does NOT contain "token", so the
    # transaction id is unaffected.
    "token",
    # PII of people who are not the person being registered. /verify returns
    # a `users` array of EVERY ABHA profile linked to that mobile -- which in
    # the live run included a different individual's name and ABHA number
    # sharing the same registered phone.
    #
    # STRICTER THAN ASKED, deliberately: this redacts fullName/abhaNumber for
    # ALL entries, not just third parties. At /verify time there is no
    # reliable way to tell which entry is the person being registered -- the
    # demographic details are not supplied until /suggestion, one call later
    # -- and a discriminator that guesses wrong fails silently in the
    # direction of leaking. abhaAddress is deliberately NOT redacted: it is
    # the thing being registered and it is what makes the archive useful.
    "fullname",
    "abhanumber",
    # Added P1-E: a raw or partially-masked Aadhaar number is exactly the
    # kind of value "mobile" and "password" were already being protected
    # as -- India's national ID number, not merely an internal identifier.
    # Matches "aadhaarNumber" (the field name several of P1-E's new flows
    # actually send/receive) as well as a bare "aadhaar" key, as a
    # substring. loginId already holds Aadhaar ciphertext for these flows'
    # REQUEST bodies and stays protected via _CIPHERTEXT_SAFE_PATHS below,
    # unaffected by this addition.
    "aadhaar",
    # Added P1-H (aegle_phr/phr/enrollment.py's enrol()): a non-blank email
    # is now RSA-encrypted before being sent under this key, the same
    # treatment mobile/password already got -- and ABHA Address creation's
    # own verify response independently carries a genuine PLAINTEXT email
    # (accounts[].email/emailVerified), confirmed live. Matches "email" and
    # "emailVerified" both, as a substring.
    "email",
)

# A three-segment base64url string beginning with a JWT header. Defence in
# depth for a token that arrives under a key the fragment list does not
# anticipate -- the key-based rule above is the primary guard.
_JWT_PATTERN = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

# Keys whose values are RSA ciphertext and are safe -- and useful -- to keep.
# Checked FIRST, because e.g. "loginId" holds ciphertext in the ABDM request
# body but would otherwise match the "loginid" fragment above.
_CIPHERTEXT_SAFE_PATHS = frozenset({"loginid", "otpvalue", "password", "mobile", "email"})


def _key_is_secret(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def redact(
    value: Any,
    plaintext_secrets: tuple[str, ...] = (),
    *,
    keep_ciphertext: bool = True,
) -> Any:
    """
    Returns a copy of `value` safe to store or log.

    Args:
        value: Any JSON-shaped structure (dict/list/scalar).
        plaintext_secrets: Exact plaintext strings to scrub by value --
            the mobile number, OTP and password handled during this call.
            Empty strings are ignored (scrubbing "" would destroy the
            whole document).
        keep_ciphertext: When True (the default, used for outbound ABDM
            request bodies), values under keys known to hold RSA
            ciphertext are preserved. Set False for anything coming from
            the UI, where those same keys hold plaintext.
    """
    secrets = tuple(s for s in plaintext_secrets if isinstance(s, str) and s != "")

    def walk(node: Any, key: str | None) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, key) for item in node]

        if isinstance(node, str):
            # JWT-shaped value, wherever it appears. Checked before the
            # key-based rule so a token under an unexpected key still goes.
            if _JWT_PATTERN.match(node):
                return REDACTED_JWT

            if key is not None and _key_is_secret(key):
                safe = keep_ciphertext and key.lower() in _CIPHERTEXT_SAFE_PATHS
                if not safe:
                    return REDACTED
            # Value-based scrub runs even on a "safe" field: if a plaintext
            # secret somehow got into a ciphertext slot, it still goes.
            scrubbed = node
            for secret in secrets:
                if secret in scrubbed:
                    scrubbed = scrubbed.replace(secret, REDACTED)
            return scrubbed

        return node

    return walk(value, None)


def contains_any(value: Any, needles: tuple[str, ...]) -> bool:
    """
    True if any needle appears anywhere in the serialised structure. Used
    by the verification pass to prove redaction actually worked, rather
    than trusting that it did.
    """
    import json

    haystack = json.dumps(value, default=str)
    return any(needle != "" and needle in haystack for needle in needles)
