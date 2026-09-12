# P1-N — Profile: Link/De-link ABHA Number, Switch Profile, QR Code, PHR Card, Refresh Token

**Model recommendation: Sonnet, extended thinking ON.** Real live-sandbox stakes (OTP-consuming
calls, an untested `DELINK` action, a genuinely undocumented-response Switch Profile step) and two
real design decisions below that need judgment, not just wiring.

## Standing design principle — this is a real app's navigation, not a pile of disconnected test screens

Aayush's own words: *"We are building an app, it might be for testing but the design has to be like
an app, I don't want to keep telling things like after login I go should go to a different page which
has my details... That is a design which should be inherent in all steps."* This is NOT scoped to
this one chunk — treat it as a standing requirement for how every screen in this app connects to
every other screen, from here forward, without needing to be told per feature.

Concretely for this chunk: every action here should leave the user somewhere sensible, never on a
raw API result they have to manually navigate away from.
- A successful Link, De-link, or Refresh Token action should return the user to the profile page
  showing the now-current state — refetch Get Profile (or otherwise update what's on screen) so a
  successful Link is actually visible on the profile view, not just confirmed by a toast that leaves
  the displayed data stale.
- Switch Profile succeeding should behave like a fresh login: it replaces the active session and
  lands the user back on the (now-different) profile/home view — exactly like finishing a login
  screen already does — not a dead-end confirmation screen with no way forward.
- QR Code and PHR Card should be reachable FROM the profile page as a natural extension of it (an
  icon/button that shows or downloads them inline), not a separately-linked, hard-to-guess route the
  user has to already know exists.
- More generally, from this chunk onward: whenever you build a screen or an action, work out where
  the user lands next and how they got there as part of building the feature itself — the way a real
  shipped app would — rather than treating navigation as an afterthought to be specified separately.
  If a genuinely ambiguous UX call comes up (e.g. inline error vs. a dedicated error state), make the
  reasonable app-like choice yourself and note it in the report, rather than leaving something
  disconnected and waiting to be told.

## What this chunk is

This finishes the PHR spec's own "PHR_Profile" section (§3.31–§3.43) that P1-M didn't cover. After
this, §3 (enrollment/login/profile) is complete and the next phase is P3 (Provider search + UIL) —
a good natural stopping point. Five API families, all requiring an already-logged-in session (a real
`X-token`, from `getSessionToken()` in `session.ts`):

1. **Link / De-link ABHA Number** (§3.31–3.36) — attach or remove an ABHA-Number identity on the
   ABHA Address you're currently logged in as, via Mobile OTP or Aadhaar OTP verification.
2. **Switch Profile** (§3.37–3.38) — for a subset of login methods only, list the other ABHA
   addresses tied to the same person and switch the active session to one of them.
3. **Get QR Code** (§3.40).
4. **Get PHR Card** (§3.41) — NOT the same thing as the ABHA card `abha_card.py` already fetches
   (P1-L) — see below.
5. **Generate Refresh Token** (§3.43).

Everything here is the SAME URL family (`/phr/app/login/profile/...`) as `profile.py`'s existing
Get/Update Profile and mobile/email/password-update work (P1-M) — same certificate
(`settings.phr_certificate_url`, 2048-bit), same header pattern (`Authorization` + `X-Token`, both,
always — see `profile.py`'s own `_headers()` and its banner for why). Do NOT use
`settings.abdm_profile_certificate_url` here; that's for the `/enrollment/...` and
`/profile/account/...` families (`aadhaar_enrollment.py`, `mobile_linking.py`,
`email_verification.py`, `abha_card.py`) — this project has already had to correct this mistake once
(P1-G→P1-J), don't repeat it.

Whether you add these functions to `profile.py` or a new sibling module (e.g.
`profile_link.py`) is your call — `profile.py` is already sizeable; a sibling module that imports
the same `_headers()`/`_encrypt()`/`_execute()` shape (duplicate the small helpers rather than
import private functions across modules, matching this project's existing per-module-helper
convention) is probably cleaner. Either way, route paths must be new and non-colliding:
`/phr/profile/link/*`, `/phr/profile/switch/*`, `/phr/profile/qr-code`, `/phr/profile/phr-card`,
`/phr/profile/refresh-token` are all currently free.

## Spec text, quoted directly (§3.31–3.43)

**§3.31 Link ABHA number via Mobile — Request OTP** — `POST /phr/app/login/profile/request/otp`.
Body: `{"scope": ["abha-login","mobile-verify"], "loginHint": "abha-number", "loginId":
"{{encrypted abha-number}}", "otpSystem": "abdm"}`. Response: `{"txnId": "...", "message": "OTP sent
to mobile number ending with ******1234"}`.

**§3.32 Link ABHA number via Mobile — Verify OTP** — `POST /phr/app/login/profile/verify`. Body:
`{"scope": ["abha-login","mobile-verify"], "authData": {"authMethods": ["otp"], "otp": {"txnId":
"...", "otpValue": "{{encrypted OTP}}"}}}`. Response (200): `txnId`, `message`, `authResult`,
`users[]` (each: `abhaAddress`, `fullName`, `abhaNumber`, `status`, `kycStatus`), `accounts[]` (a
much richer per-account object — demographics, `profilePhoto` AND `kycPhoto` as separate base64
blobs, `authMethods[]`, `verificationStatus`/`verificationType`, `preferredAbhaAddress`, an empty
`tags: {}`), and `tokens` (`token`, `expiresIn: 1800`, `refreshToken`, `refreshExpiresIn: 1296000`).
**Live Postman confirms a real quirk**: the `users[]` entries use lowercase `abhaNumber`, but the
`accounts[]` entries use PascalCase `ABHANumber` — same response, different casing for the same
concept in two different arrays. Don't normalize this away silently; if you build a typed response
model, accept both spellings defensively (mirroring `first_present()`'s pattern already used
elsewhere in this project, e.g. M1's `profile_utilities.py`). Also confirmed live: a wrong/expired
OTP can come back as **HTTP 200** with `authResult: "failed"` and empty `users: []` — not always a
4xx — so don't treat a non-2xx status as the only failure signal for this call.

**§3.33 Process Link Request via ABHA number** — `POST /phr/app/login/profile/link`. Body:
`{"action": "LINK", "transactionId": "{{transactionId}}"}` (the `transactionId` here is the `txnId`
from the verify step above). Response: `{"message": "ABHA number is securely linked to ABHA
address", "authResult": "success"}`.

**§3.34/3.35/3.36** — identical trio for Aadhaar-OTP verification instead of Mobile-OTP: same
`/request/otp` and `/verify` URLs, `scope: ["abha-login","aadhaar-verify"]`, `otpSystem: "aadhaar"`,
same `/profile/link` process step. Live Postman confirms the verify response shape is identical to
§3.32's (same `users[]`/`accounts[]`/`tokens`, same casing quirk).

**De-link — NOT separately documented, and NO saved Postman example exists for it either.**
Checked directly against the live Postman collection (a subagent searched the entire ~2.5M-character
export, not just this folder): every saved example anywhere in the collection uses
`"action": "LINK"` — never `"DELINK"`. The ONLY evidence a `DELINK` action is real at all is a saved
error example named "Link Request – Invalid Account Action" (400, `{"code":"ABDM-9999:
","message":"Invalid Account Action"}`) on the same `/profile/link` endpoint, which implies the
endpoint validates `action` against a set of allowed values (presumably including `DELINK`) but
nobody on this team ever captured a working de-link call. **Working hypothesis, flagged, not
proven**: de-link reuses the exact same OTP request/verify dance as link (§3.31/3.32 or 3.34/3.35),
then calls `/profile/link` with `"action": "DELINK"` instead of `"LINK"`. Build it this way, but
treat it as genuinely unverified — if it 400s with something other than "Invalid Account Action",
don't guess further (don't try alternate field names, alternate endpoints, etc.) — surface the raw
error response in the report and stop there; this is exactly the kind of thing to flag rather than
paper over.

**§3.37 Switch Profile Request** — `GET /phr/app/login/profile/switch-profile`. No documented
response body in the spec itself (blank in the doc) — **live Postman fills this gap**: a real
343KB captured response containing `txnId` plus a `users[]` array (dozens of real ABHA
addresses/profiles for the account — `fullName`, `status`, `kycStatus`, often a base64
`profilePhoto`, inconsistently present/absent/PNG-vs-JPEG across entries — this is real captured
data, heterogeneous, not a clean template; don't assume every entry has every field) and a `tokens`
object (`token`, `expiresIn: 300`, `refreshToken: null`, `refreshExpiresIn: null` — the `expiresIn:
300`/no-refresh-token shape matches this project's own established "transient token" pattern, e.g.
`verify_user()`'s T-token — treat this response's `tokens.token` as the T-token to use in the verify
step below).

**Governing rule, quoted directly, must gate the UI, not just be mentioned**: *"If a user logs in
using an ABHA Address, they will not be able to switch between different users. If a user logs in
using an ABHA Number, AADHAAR Number, or Mobile Number, they can switch between profiles."* — see
the session.ts change required below; this can't be enforced without knowing how the current session
was established, which nothing in this app currently tracks.

**§3.38 Switch Profile Verify** — `POST /phr/app/login/profile/verify/switch-profile/user`. Body:
`{"abhaAddress": "chosen@sbx", "txnId": "{{transactionId from the Request step}}"}`. **Header is
`T-token`, not `X-token`, for this one call** — confirmed by both the spec and live Postman (the
switch-profile GET step above still uses `X-token`; only this verify step differs). Response (spec
blank, live Postman confirms): `{"token": "...", "expiresIn": 1800, "refreshToken": "...",
"refreshExpiresIn": 1296000}` — **note this is a BARE top-level `token`, not nested under
`tokens{}`** like every other verify-style response in this project. `extractSessionToken()` in
`session.ts` currently REQUIRES a `tokens` wrapper and will return `null` for this shape — either add
a second extractor or a shape-detecting branch; don't force this response through the existing
function unmodified, it will silently fail.

**§3.39/§3.42** — Get/Update Profile, already built in P1-M, untouched by this chunk.

**§3.40 Get QR Code** — `GET /phr/app/login/profile/qrCode`. Spec: "Status code: 202 Accepted",
response labeled just "QR Code". **Live Postman's saved example is a 202 with a literal placeholder
body, the 7-character string `"QR Code"`** — not real image/binary/base64 data. Treat this as
non-authoritative for the real payload shape; build defensively (see below).

**§3.41 Get PHR Card** — `GET /phr/app/login/profile/phrCard`. Spec: *"PHR card will display
(eKYC/non-eKYC) user details. Note: To generate the PHR card, the ABHA address is a mandatory field,
but the ABHA number is optional. However, for the ABHA card, both the ABHA number and ABHA address
are mandatory."* This is explicitly a DIFFERENT card from the ABHA card `abha_card.py` (P1-L)
already fetches (`/profile/account/abha-card`, needs both ABHA number AND address, chained off a
fresh Aadhaar-enrollment transaction token) — this one needs only an address, on a real logged-in
session, different URL family, different certificate. Don't touch or reuse `abha_card.py`; this is a
new, parallel capability. Live Postman's saved example is likewise a 202 with a placeholder
8-character string `"PHR Card"`, not real data — same caveat as QR Code.

**Building the QR/PHR-card response handling**: since neither saved example is real payload data,
the actual live response shape (binary image? base64 JSON? PDF?) is unconfirmed until you run it.
M1's own `profile_utilities.py` (`repo/tools/m1_test_suite/flows/profile_utilities.py`) has a useful
PATTERN worth adapting even though its endpoints are a different family — `_save_binary()` reads
`response.headers["Content-Type"]`, maps it to a file extension (`application/pdf`→.pdf,
`image/png`→.png, `image/jpeg`→.jpg, else `.bin`), and saves the raw bytes rather than assuming
JSON. Mirror that defensiveness here: don't call `.json()` unconditionally on these two responses.

**§3.43 Generate Refresh Token** — `GET /phr/app/login/profile/request/token`. Header is
**`R-token`, not X-token** (a third distinct token-header name in this family, alongside `X-token`
and `T-token`) — `Authorization: Bearer <R-token>`-style per spec (`R-token | Bearer {{R-token}}`).
No request body (spec's own property table for this section is a copy-paste leftover from a
different endpoint — "status/consentId/error/requestId" — clearly wrong for a GET with no body;
ignore it). Response: `{"tokens": {"token": "...", "expiresIn": 1800, "refreshToken": "...",
"refreshExpiresIn": 1296000}}`. **Live Postman's saved example has `refreshToken: ""`** (empty
string, not a new token) — whether the real API actually rotates the refresh token or always returns
it empty is unconfirmed by the saved data; don't assume either way, just handle whatever comes back
(if it's empty, `session.ts`'s stored refresh token — see below — simply doesn't get replaced).

## A design decision that needs solving before Switch Profile OR Refresh Token can work, flagged not silently decided

`session.ts`'s own banner currently says: *"refreshToken -> NEVER stored anywhere, not even here...
this harness has no refresh flow to use it... nothing in this module has a slot for it."* That was a
deliberate, correct decision **at the time** — but this chunk is exactly the "refresh flow" that
justification was waiting for. Recommendation: reverse that specific piece of the decision now that
a real consumer exists — store `refreshToken` in `sessionStorage` alongside the existing token (same
lifetime/security posture already accepted for the token itself: cleared on tab close, not persisted
to disk), and update the file's own banner to explain why the earlier reasoning no longer applies.
Add a "Refresh Session" affordance somewhere reachable from the profile screen that calls this
chunk's refresh-token endpoint and re-`setSession()`s with whatever comes back.

Separately: `session.ts` currently has **no concept of which login method established the current
session** — every login screen just calls `setSession(address, token)`. The Switch Profile gating
rule above (ABHA-Address logins can't switch; Number/Aadhaar-Number/Mobile logins can) is
unenforceable without this. Add a third piece of session state — e.g. `setSession(abhaAddress,
token, loginMethod)` with `loginMethod` a small literal union (`"abha-address" | "abha-number" |
"aadhaar-number" | "mobile" | "password"` — match whatever the existing login screens already
distinguish internally) — and update every existing login screen's `setSession()` call to pass it
(P1-M's ProfileScreen didn't need this, so it wasn't added then). Use it to hide the Switch Profile
entry point entirely for ABHA-Address-established sessions, matching the spec's own note rather than
letting the user find out via a live API error.

## What to build

- **Link/De-link ABHA Number**: two verification sub-methods (Aadhaar OTP, Mobile OTP) — mirror the
  existing two-sub-method UI pattern already used in `AbhaAddressCreationScreen.tsx` (P1-H) rather
  than inventing a new one. One screen or panel, reachable from the profile page, offering
  Link-or-De-link (radio/toggle) × (Aadhaar-OTP or Mobile-OTP), each running request→verify→process
  in sequence, surfacing the real result message.
- **Switch Profile**: request step lists the account's other ABHA addresses (guarded by the
  `loginMethod` check above); user picks one; verify step swaps the active session via `setSession()`
  with the new address/token — after which the whole app (nav, profile page) should reflect the
  newly active identity, same as a fresh login would.
- **QR Code / PHR Card**: fetch-and-display (or fetch-and-download, matching whatever's simplest
  given the actual live Content-Type once you've seen it) from the profile page.
- **Refresh Token**: a "Refresh Session" action, per the design decision above.

## Explicitly NOT in scope

Logout is already built (`App.tsx`'s own `logout()`, wired to nav) — nothing to add there. Nothing
from P1-M (Get/Update Profile, mobile/email/password updates) should be touched. `abha_card.py` /
`mobile_linking.py` / `email_verification.py` / `aadhaar_enrollment.py` stay untouched — different
URL families, different problems, already explained above.

## Verification

Offline: read every new/changed file back, confirm cert/header choices match the URL-family rule,
confirm routes don't collide with the existing list in `api.py`, confirm `session.ts`'s
`extractSessionToken()` change (or new sibling function) handles BOTH the wrapped-`tokens` shape and
Switch-Profile-Verify's bare-`token` shape without one silently breaking the other's callers.

Live (ask permission before each OTP-consuming or session-mutating step; these are real, not
sandboxed against a mock):
1. Get QR Code and Get PHR Card first — no OTP cost, free to retry, and resolves the real response
   shape question above.
2. Link ABHA Number (either method) against the current test account — report the real
   `users[]`/`accounts[]` shape you actually got back, confirm the casing quirk is real and not just
   a stale Postman capture.
3. De-link, immediately after, using the transactionId pattern above — this is the genuinely unknown
   one; report exactly what happens, success or failure, verbatim.
4. Switch Profile — needs a login method that qualifies (not ABHA-Address) and an account with more
   than one linked address; if `chordiaaayush1997@sbx` or the current test account doesn't have a
   second address available, say so rather than fabricating a positive result.
5. Refresh Token — confirm whether a new refresh token actually comes back or the empty-string
   pattern from the Postman capture holds live.

## Ground rules (standard, repeated)

No throwaway scripts left behind. Detailed per-file change report plus a short Cowork-pasteable
summary. Strict scope discipline — flag anything else you spot, don't fix it, only fix bugs you
introduce this chunk. No git commit/push/init. Never delete/truncate existing `logs/`/`storage/`
content. Don't claim something works without running it. Flag uncertainty visibly, especially
around: the DELINK hypothesis, the real QR/PHR-card payload shape, and whether Switch Profile is
even exercisable given the test accounts available. Never print the access key, client secret,
plaintext OTP, mobile number, email address, password, or any live token into any report. Do not
modify `repo\` (read-only reference). Headers: `Authorization` (gateway) + `X-Token` for every call
in this chunk EXCEPT Switch-Profile-Verify (`T-token` instead) and Refresh Token (`R-token` instead)
— three different header names across five API families, don't default to one everywhere.
