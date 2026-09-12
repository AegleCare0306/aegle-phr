# Claude Code prompt — P1-C: password login

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

Wire the first real login method into the `/login` shell built in P1-B: **password login** for an
ABHA address created via mobile enrollment (P1-A).

## Why this one first

Every other login method sends an OTP — real SMS, real rate limits, the same lockout risk P1-A had
to work around. Password login sends nothing: it's the one flow that can be run, broken, and re-run
as many times as needed without touching the sandbox's SMS limits. It also completes the loop —
`aayushchordia1997`-style addresses created in P1-A become genuinely testable end to end for the
first time.

Test account: `chordiaaayush1997@sbx` (created in P1-A) plus its password, which I'll supply when
I run the live check — same rule as P1-A, don't invent it or guess it.

## The flow — three ABDM calls, base URL `settings.abdm_abha_base_url`

All three take `REQUEST-ID`, `TIMESTAMP`, `Authorization: Bearer <gateway token>` — same as P1-A.

### 1. Search user — `POST /phr/app/login/search`
```json
{ "abhaAddress": "chordiaaayush1997@sbx" }
```
**Documented response**, `200`:
```json
{ "healthIdNumber": "...", "abhaAddress": "...", "authMethods": ["MOBILE_OTP","PASSWORD",...],
  "blockedAuthMethods": [], "status": "ACTIVE", "message": null }
```
Documented error: unknown address → `400`, `{"code": "ABDM-1211", "message": "User not found."}`.
Use `authMethods` to confirm `PASSWORD` is actually available for this address before showing the
password field — don't assume it always is.

### 2. Verify password — `POST /phr/app/login/verify`
```json
{ "scope": ["abha-address-login", "password-verify"],
  "authData": { "authMethods": ["password"],
                "password": { "abhaAddress": "chordiaaayush1997@sbx",
                               "password": "<RSA-encrypted>" } } }
```
**Response shape UNDOCUMENTED** — same gap pattern as P1-A's `verify`/`enrol`: the spec gives error
cases only (wrong password → `200` with `{"message": "Password did not match, please try again",
"authResult": "failed", "users": []}`; blank password → `400` array). **Do not invent the success
shape.** Expect something resembling mobile's `verify` (a `users` list, possibly a short-lived
transfer token) based on the pattern so far, but capture and record what actually comes back rather
than assuming.

### 3. Verify user (get the real session) — `POST /phr/app/login/verify/user`
```json
{ "abhaAddress": "chordiaaayush1997@sbx", "txnId": "<txnId from step 2>" }
```
**Documented response**, `200`:
```json
{ "token": "...", "expiresIn": 1800, "refreshToken": "...", "refreshExpiresIn": 1296000 }
```
This is the real X-token grant. The spec describes this endpoint as generic — "verify the user from
the list of ABHA addresses received in the response of verify OTP/face authentication API" — so it's
likely reused by every other login method later, not password-specific. Build it as a standalone
function for that reason.

## Encryption, archive, redaction — reuse P1-A's, don't rebuild

Same certificate, same helper: `get_public_certificate(settings.phr_certificate_url)` /
`encrypt_value` from `abdm_core.rsa_crypto`, exactly as P1-A used them.

Route these three calls through `abdm_call_log` exactly like P1-A's enrollment calls, using
`aegle_phr/phr/redaction.py` as-is. It already redacts `password`, any JWT-shaped value, and
`fullname`/`abhanumber` wherever they appear — this flow shouldn't need new redaction rules, but if
you find a field it doesn't cover, say so rather than silently leaving it exposed.

## Session storage — decided, not a design choice for you to make

The P1-A/P1-B reports both flagged that a login token is a JWT carrying PII (mobile, name, DOB) in
its claims — unlike the access key, which is an opaque string. Treat it accordingly:

- **`token` (the 30-minute X-token): `sessionStorage`, not `localStorage`.** It clears when the tab
  closes rather than persisting indefinitely on the tester's machine. Mask it in any UI the same way
  the access key is masked.
- **Do not persist `refreshToken` at all.** It's valid 15 days — far longer than this harness needs,
  and there's no refresh-flow being built in this chunk to use it. Hold it in memory only for the
  duration of the session if you need it for anything; if you don't need it for anything, don't even
  keep it past the response that returned it. If a tester's session expires, they log in again —
  that's cheap and correct for a throwaway harness.
- The access key's existing `localStorage` treatment is unaffected — it stays as-is. This is a
  narrower rule for login tokens only, because they carry PII the access key doesn't.

## Backend structure

New `aegle_phr/phr/login.py` — one function per call, same shape as `enrollment.py`: parsed body +
status code, wrapped in `call_with_retry` where appropriate. Note in your report whether retrying
`verify` (wrong password) is safe to wrap — unlike an OTP request, a wrong password doesn't cost an
SMS, so the calculus from P1-A's "don't retry OTP requests" rule doesn't automatically transfer; make
a call and say why.

New routes on the app-API router (gated, same as P1-A's):
```
POST /phr/login/search
POST /phr/login/verify
POST /phr/login/verify-user
```

## UI

Wire `/login/mobile` is NOT this — that stays "not built yet". Password login needs its own entry
point. Add it to the `/login` page from P1-B as a clearly separate option (e.g. "Login with
password" alongside the three method links and the Enroll link) routing to a new screen with:

1. ABHA address input → Search (shows `authMethods` back, confirms `PASSWORD` is offered).
2. Password input (`type="password"`, never in `localStorage`) → Verify.
3. On success, call Verify User with the returned `txnId`, store the resulting `token` per the rule
   above, and show a plain "Logged in as `<abhaAddress>`" state — no dashboard, no further screens,
   that's out of scope here.

Every call goes through `client.ts`, same as every other screen. Follow P1-B's "adding a route"
recipe.

---

## Verification

**Offline, mocked — all of this first:**
1. Request bodies for all three calls match the shapes above exactly, field by field, against a
   mocked transport.
2. `encrypt_value` is called with `settings.phr_certificate_url`, matching P1-A.
3. `sessionStorage` (not `localStorage`) holds `token`; `refreshToken` is never written to any
   browser storage — grep the built bundle and runtime behavior to prove it, don't just assert it.
4. Redaction: drive a call with a known plaintext password and assert it never appears in
   `abdm_call_log`, reusing the same proof technique as P1-A (`redaction.contains_any`).
5. All three new routes are on the gated router — 401 without `X-Aegle-Key`.
6. `tsc --noEmit` and `npm run build` clean; `grep fetch(` still only in `client.ts`.

**Then one live sandbox run:**
7. Stop and ask me for the password for `chordiaaayush1997@sbx` before making any live call. Walk
   search → verify → verify-user once. No SMS involved, so no OTP-style one-shot restriction — but
   still don't loop or retry blindly; if something fails, stop and report before trying again.

Report, verbatim, the actual response body of `verify` (redacting the token/password values but
describing their presence and shape) — this is the chunk's real documentation deliverable, same as
P1-A's captured-shapes work. Add it to `aegle-phr/README.md` under the existing "Captured ABDM
response shapes" section, marked observed-once.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — password login only. Flag anything outside it, don't fix it. Fix bugs
   you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — the `verify` success shape is undocumented; say so in code and report.
8. Do not modify `repo\` or `aegle-abdm-core\`.
9. Never print the access key, the client secret, a plaintext password, or a live token into your
   report.
