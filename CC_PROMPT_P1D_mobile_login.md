# Claude Code prompt — P1-D: mobile OTP login

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

Wire the second login method into the `/login` shell: **login via mobile OTP** (spec §3.11-3.12).
This fills in the `/login/mobile` route, currently the honest "Not built yet" stub from P1-B.

## Why this one next, and what's different from password login

This is the first real exercise of `verify_user()` — built in P1-C, never called, because password
login already knew exactly which ABHA address it was logging into. Mobile login doesn't: the spec
says its `verify` step returns **every ABHA address linked to that mobile number** ("all the ABHA
addresses linked to the mobile number will be displayed"). My test number has 5+ linked addresses
(seen in P1-A's enrollment `verify`), so this is a real multi-account disambiguation, not a
hypothetical one.

**⚠️ Unlike password login, this one sends a real SMS.** Same rule as P1-A: request the OTP once,
verify once, do not loop or retry the request step. If something fails partway, stop and tell me
rather than immediately re-requesting.

## The flow — three ABDM calls

### 1. Request OTP — `POST /phr/app/login/request/otp`
```json
{ "scope": ["abha-address-login", "mobile-verify"],
  "loginHint": "mobile-number", "loginId": "<RSA-encrypted mobile>", "otpSystem": "abdm" }
```
Documented response: `200` with `{txnId, message}`.

### 2. Verify OTP — `POST /phr/app/login/verify`
```json
{ "scope": ["abha-address-login", "mobile-verify"],
  "authData": { "authMethods": ["otp"],
                "otp": { "txnId": "<txnId>", "otpValue": "<RSA-encrypted OTP>" } } }
```
**Success shape UNDOCUMENTED** (spec leaves it blank, same gap as every other `verify` so far).
Documented error case for a wrong OTP is useful context even though it's not success:
`{txnId, message: "Entered OTP is incorrect...", authResult: "failed", users: []}` — so the success
shape almost certainly includes `users: [...]` (the linked-addresses list) and probably a `txnId` to
carry into step 3, unlike password login. **Confirm this from the real response, don't assume the
shape from the error case.**

### 3. Verify user — `POST /phr/app/login/verify/user` (already built in P1-C, unused until now)
```json
{ "abhaAddress": "<the address the person picked>", "txnId": "<from step 2>" }
```
Documented response: `{token, expiresIn: 1800, refreshToken, refreshExpiresIn: 1296000}`.
Use `aegle_phr/phr/login.py`'s existing `verify_user()` as-is — do not rewrite it. If step 2's
response genuinely has no usable `txnId` the way password login's didn't, stop and report rather
than guessing a substitute; that would be a second real spec finding worth the same treatment as
P1-C's.

## Reuse everything already built — this chunk is mostly wiring, not new plumbing

- RSA encryption against `settings.phr_certificate_url`, same as every prior chunk.
- `abdm_call_log` archiving via the same `_execute()` machinery in `login.py`.
- **Apply `login.py`'s `extra_response_secrets` pattern to this call's `verify` step too.**
  P1-C found ABDM returning an undocumented plaintext `mobile` field on a *different* login
  response than the one it was first fixed for — treat that as the standing lesson, not a one-off:
  check this endpoint's actual response for any plaintext identifying field before assuming the
  existing redaction rules cover it, and extend the extractor if they don't.
- Session storage: `session.ts` as built in P1-C, unchanged — `token` to `sessionStorage`,
  `refreshToken` never persisted. No new design decision needed here.
- Retry policy: match P1-A/P1-C precedent — don't retry the OTP request step; default retry is fine
  for `verify` and `verify_user` (same structural reasoning already used and documented for
  `verify_password`). State explicitly if you deviate and why.

## New UI work

`/login/mobile` replaces its stub with:
1. Mobile number input → Request OTP.
2. OTP input (`type="password"`) → Verify. Response's `users[]` renders as a **list to pick from**
   — this is the new piece password login didn't need. Show enough per entry to distinguish them
   (`abhaAddress` at minimum; `status`/`kycStatus` if present) — but redact/mask anything sensitive
   the same way the Console panel already does, since this list may include profiles beyond the one
   being logged into.
3. Picking one calls `verify_user` with that `abhaAddress` + the `txnId`, stores the session via the
   existing `session.ts` functions, and lands on the same plain "Logged in as `<address>`" state
   `PasswordLoginScreen` uses — reuse that pattern/component shape rather than inventing a new one.

Follow the P1-B "adding a route" recipe. `fetch()` stays isolated to `client.ts`.

---

## Verification

**Offline first:**
1. Request bodies match the shapes above field-by-field against a mock.
2. `verify_user` (existing code) is called unmodified, with a real `abhaAddress`/`txnId` pair.
3. Redaction: confirm whatever P1-C's `extra_response_secrets` pattern needs extending to cover
   this endpoint's actual fields — prove it with `redaction.contains_any()`, not by inspection alone.
4. `sessionStorage`/`localStorage` split unchanged from P1-C — reconfirm it, don't just assume it
   still holds after adding a new screen.
5. All routes 401 without `X-Aegle-Key`.
6. `tsc --noEmit` and `npm run build` clean; `fetch(` still only in `client.ts`.

**Then one live sandbox run:**
7. Stop and ask me for the mobile number and to read back the OTP, same as P1-A. Walk request →
   verify → (pick an address) → verify_user once.

Report, verbatim, the actual `verify` response body (redact token/mobile-type values, describe
their presence and shape) — same documentation deliverable pattern as every prior chunk. Add it to
`aegle-phr/README.md`'s captured-shapes section. Explicitly answer: does `verify`'s success response
include a usable `txnId`, and does its `users[]` list match the shape already seen in P1-A's
enrollment `verify`, or differ?

If the live run fails, stop and report — do not re-request an OTP.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — mobile login only. Flag anything outside it, don't fix it. Fix bugs
   you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially the `txnId` question in step 2/3.
8. Do not modify `repo\` or `aegle-abdm-core\`.
9. Never print the access key, the client secret, a plaintext OTP, a mobile number, or a live token
   into your report.
