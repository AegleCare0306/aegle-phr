# Claude Code prompt — P1-D fix: verify_user 401 (missing T-Token header)

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

This is a small, scoped patch to the P1-D mobile-login work, not a new chunk. It fixes the real 401
`verify_user` hit on its live run: `POST /phr/app/login/verify/user` returned a genuine 401 (297ms,
empty body, request payload correct) when called with only `Authorization: Bearer <gateway_token>`.

## The finding — evidence, not a guess this time

The PHR spec's own header table for `verify/user` (§3.25) lists only `Authorization`, `REQUEST-ID`,
`TIMESTAMP`. But that same section's error-scenario table has a row: *"When passing without T token
→ 403 Forbidden"* — referencing a "T token" that never appears in the header table. That's the spec
being internally inconsistent, not proof of anything by itself.

What resolves it: a separate, related ABDM Postman collection (the older core-ABHA/Health-ID API,
`v1`/`v2`, same vendor conventions, already the basis for the M1 flow in `repo/`) has the equivalent
step for its own mobile-login flow — `POST .../v2/registration/mobile/login/userAuthorizedToken` —
and its headers are `accept, Accept-Language, Content-Type, T-Token: Bearer T-Token` — **no
`Authorization` at all**. The same collection consistently uses three distinct token headers across
the whole login lifecycle: `Authorization` (gateway/client token, used through OTP verification),
`T-Token` (the short-lived transfer token, used specifically for the token-claiming step), `X-Token`
(the final session token, used for everything after login). This maps directly onto what our own
`verify_mobile_otp()` (step 2) already receives back — `tokens.token`, `expiresIn: 300`,
`"typ": "Transfer"` — a transfer token we currently capture and then discard.

**Working theory to test**: `verify_user()` needs an additional `T-Token` header carrying step 2's
transfer token, alongside (not instead of) the existing `Authorization: Bearer <gateway_token>` —
the spec's header table for `verify/user` may simply be incomplete, matching the pattern already
seen twice in this project (P1-A/P1-C both found `verify` response shapes the spec left undocumented
or wrong).

## What to change

1. `login.py`'s `verify_user()` — add an optional parameter for the transfer token (e.g.
   `transfer_token: str | None`). When provided, add a header to the request. **Try the exact form
   seen in the sibling collection first**: header name `T-Token`, value `f"Bearer {transfer_token}"`.
   Keep the existing `Authorization: Bearer <gateway_token>` header unchanged — this is additive, not
   a replacement, unless the live test proves otherwise.
2. Wire the transfer token through: `verify_mobile_otp()`'s response already has `tokens.token` —
   thread it from wherever step 2's response is held (backend response or the frontend, whichever is
   the natural seam given how `/login/mobile` currently calls step 2 then step 3) into the call to
   `verify_user()` / the `/phr/login/verify-user` route. State plainly which layer you chose and why.
3. **Redaction — check this explicitly, don't assume.** The transfer token is a JWT going out in a
   *request header* now, not a body field. Check whether `abdm_call_log` archiving captures request
   headers at all (if it only archives bodies, there's nothing to redact here and say so); if it does
   capture headers, confirm the JWT-shape regex in `redaction.py` (or the existing `Authorization`
   handling, if that's already redacted) also covers a `T-Token` header value. Prove it with a real
   assertion, not by inspection alone.

## Testing it live

The `txnId`/transfer-token pair from the earlier 401 run is almost certainly expired by now — its
transfer token had a 300-second TTL and a lot of investigation happened since. **Assume you need a
fresh OTP cycle**, not a reused one. Same one-shot ground rules as every other live OTP test in this
project: request once, verify once, don't loop. Stop and ask me for the mobile number and to read
back the OTP, same as every prior live run.

Sequence: request OTP → verify OTP (capture the transfer token from this response) → verify_user
with the `T-Token` header added → report the exact result.

- **If this fixes it (200 with `{token, expiresIn, refreshToken, refreshExpiresIn}`)**: capture the
  full response shape (redacting token values but describing their presence/shape) for
  `aegle-phr/README.md`'s captured-shapes section, same as every prior chunk's documentation
  deliverable. Note explicitly that the PHR spec's header table for `verify/user` (§3.25) is missing
  a required header — worth recording as a spec gap alongside the others already tracked (R11-R13
  style).
- **If it still 401s**: try once more without the `Bearer ` prefix (just the raw transfer-token
  string as the header value) — the sibling collection's literal example value (`"Bearer T-Token"`)
  is a placeholder, not necessarily proof the real value needs the prefix. `verify_user` is stateless
  and already established as safe to retry (no SMS), so trying both forms in the same live run is
  fine. If both forms fail, stop and report the exact response (status, headers, body) for both
  attempts — do not guess a third variant on your own.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — this header fix only. Flag anything else you spot, don't fix it. Fix
   bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially if neither header form fixes the 401.
8. Do not modify `repo\` or `aegle-abdm-core\`.
9. Never print the access key, the client secret, a plaintext OTP, a mobile number, or a live token
   into your report.
