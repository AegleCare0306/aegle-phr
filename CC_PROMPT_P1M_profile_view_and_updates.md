# Claude Code prompt — P1-M: profile page (view) + profile updates (mobile, email, password)

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

> Read this whole prompt before touching code — several parts of it correct a mistaken assumption an
> earlier draft of this prompt made, using live evidence pulled directly from Aayush's own Postman
> account just before this was written. Everything below is grounded in either the PHR spec
> (`ABHA_PHR_V3_Documents`, §3.26-§3.30 and §3.39/§3.42) or a real saved example in the "PHR"
> collection in Aayush's Postman workspace — nothing here is guessed. Where spec and Postman
> disagreed, that's called out explicitly with which one this prompt trusts and why.

---

## Where this fits

Login (one method — mobile), ABHA Number creation via Aadhaar, and ABHA Address creation for an
existing ABHA Number are all built and Aayush has tested them live. **Next**: once a user is logged
in, the app should show a profile page (photo if available, ABHA Number, ABHA Address, KYC badge —
matching the reference screenshot Aayush shared) with an edit affordance that lets them update mobile,
email, and password — demographic fields (name/DOB/gender) show but are only actually editable when
ABDM says they're allowed to be.

**This app has no shared "logged in" home screen yet** — every existing screen (`AadhaarRegisterScreen`,
`AbhaAddressCreationScreen`, `PasswordLoginScreen`, `OtpLoginScreen`) manages its own local
logged-in-or-not view, and the nav is "every route reachable directly, no real signed-in/signed-out
state" (see `App.tsx`'s own comment). This chunk adds the first screen whose entire purpose IS the
logged-in state — build it as a new top-level route/nav link (e.g. `/profile`) that reads the same
`getSessionToken()`/`session.ts` every other screen already uses, and shows a plain "log in first"
message if empty, matching the guard pattern `AadhaarRegisterScreen.tsx` already uses for its own
bridge data.

**One relevant fact for live testing, not a blocker to fix**: nothing in this app currently sets a
password during registration (an earlier version tried; removed — see `AadhaarRegisterScreen.tsx`'s
own banner, "password is a LOGIN mechanism, not part of registration"). For live-testing Update
Password, use the original P1-A test account (`chordiaaayush1997@sbx`), which already has one set.

## The five ABDM calls this chunk needs — request/response shapes, certificate, headers

### 1 · Get Profile — §3.39, `GET /abha/api/v3/phr/app/login/profile`

Confirmed identically by the spec AND a real saved Postman example (`"PHR" → "PHR Profile" → "Get
Profile"`, 200 OK, real account `hemant.bodhai_test@sbx`) — full field list:
```
abhaAddress, fullName, firstName, middleName, lastName, dayOfBirth, monthOfBirth, yearOfBirth,
dateOfBirth, gender, email, mobile, abhaNumber, address, stateName, districtName, pinCode, stateCode,
districtCode, authMethods[], status, emailVerified, mobileVerified, kycStatus, abhaLinkedCount
```
**There is no photo field anywhere in this response — confirmed twice** (spec's own example, and the
live saved Postman example). If Aayush's reference screenshot shows a photo, that photo did not come
from this call. **Do not fetch a photo from anywhere else and do not fabricate a placeholder.** Check
whether this session already captured one somewhere reachable (`enrol/byAadhaar`'s own `ABHAProfile`
response has a `photo` field, per `aegle_phr/phr/aadhaar_enrollment.py` — but that data is
transaction-scoped to registration and nothing currently persists it past the registration screens).
**State plainly in your report whether a photo is shown at all, and where it came from if so** — if
none is available for however the user actually logged in, render the profile page without one rather
than guessing.

### 2 · Update Profile — §3.42, `POST /abha/api/v3/phr/app/login/profile/updateProfile`

**The exact ANSWER to Aayush's editable/non-editable question, quoted directly from the spec**:
*"In the case of an e-KYC user, KYC details such as name, DOB, and gender will not be updated.
However, for a non-e-KYC user, all details will be updated."* Read `kycStatus` from the Get Profile
response you already fetched: **`"VERIFIED"` → lock `firstName`/`middleName`/`lastName`/`dayOfBirth`/
`monthOfBirth`/`yearOfBirth`/`gender` as display-only, not editable. Anything else (`"PENDING"` or
otherwise) → all of those fields ARE editable.** `address`/`stateName`/`districtName`/`pinCode`/
`stateCode`/`districtCode`/`profilePhoto` are not covered by this restriction — always editable,
regardless of KYC status.

**A real discrepancy this prompt resolves, don't rediscover it**: the spec's own property table for
this endpoint lists `Email` and `Mobile` as request fields, but its own illustrative JSON example
omits both. The live Postman collection's actual saved request body (`"PHR" → "PHR Profile" →
"Update Profile"`) **does include both** `"email"` and `"mobile"` alongside every demographic field —
trust that over the spec's incomplete JSON example, matching this project's established rule
(a real captured request/response beats a spec example every time they disagree).

**Working hypothesis for `mobile`/`email` here — confirm live, don't assume it's right**: since
dedicated OTP-verified endpoints exist specifically for changing mobile and email (items 3 and 4
below), the most sensible read is that `updateProfile` needs those two fields **present but
unchanged** (echoing whatever Get Profile already returned) rather than being a second, unverified way
to change them. Build it that way — the profile-edit screen never lets the user type into a
mobile/email field directly; those stay display-only there, with a distinct "Update mobile" / "Update
email" action elsewhere on the page routing to items 3/4 below. **Test this live**: submit an
`updateProfile` call with a demographic change but the mobile/email fields unchanged, and separately
(if you want real certainty and Aayush approves the extra call) try submitting a *different* value in
one of them to see whether ABDM actually accepts a silent, unverified change or rejects/ignores it.
Report which you found, plainly — don't leave this as a silent assumption in the shipped code.

Success response — confirmed identical shape to Get Profile's, per a real saved Postman example.
Error scenarios (from the spec, worth porting the shape check for): invalid first name, invalid
DOB (400, array of `{code, message}`), blank state/district (400), no X-token (403), no auth (401).

**The "Update" affordance only activates once something has actually changed** — Aayush's explicit
instruction. Diff the editable fields' current values against what Get Profile returned; only enable
submission (and probably only send the fields that actually changed, or all of them unchanged-if-untouched
— your call, state which) once at least one editable field differs from its fetched baseline.

### 3 · Update Mobile — §3.26/§3.27, request/verify pair

**Do NOT reuse `aegle_phr/phr/mobile_linking.py` for this — read its own module banner before
assuming otherwise.** That module intentionally targets a *different* ABDM URL family
(`/enrollment/request/otp` + `/enrollment/auth/byAbdm`) because it chains off a **transaction-scoped**
token from a fresh Aadhaar enrollment, not a real logged-in session — confirmed live (its banner
documents a real "Invalid X-token" failure when it first tried the URL family this chunk actually
needs). **This chunk's context is different and the original approach is correct here**: a genuinely
logged-in user, holding a real session `X-token`, updating their already-established profile. This is
independently confirmed working by a real saved Postman example, not just the spec:

- Request OTP: `POST /abha/api/v3/phr/app/login/profile/request/otp`,
  `{scope: ["abha-address-profile","mobile-verify"], loginHint: "mobile-number", loginId: <encrypted
  new mobile>, otpSystem: "abdm"}`.
- Verify OTP: `POST /abha/api/v3/phr/app/login/profile/verify`,
  `{scope: ["abha-address-profile","mobile-verify"], authData: {authMethods: ["otp"], otp: {txnId,
  otpValue: <encrypted OTP>}}}` → confirmed success: `{txnId, message: "Mobile Number linked
  successfully", authResult: "success", users: [{abhaAddress}]}` (this exact shape is in a real saved
  Postman response, not just the spec).

### 4 · Update Email — §3.28/§3.29, request/verify pair

Same shape as mobile, `scope: ["abha-address-profile","email-verify"]`, `loginHint: "email"`,
confirmed success: `{txnId, message: "Email linked successfully", authResult: "success", users:
[{abhaAddress}]}` — also a real saved Postman response, not just the spec. **This is a separate,
new module from `aegle_phr/phr/email_verification.py`** — that one is a fire-and-forget clickable-link
email (`/profile/account/request/emailVerificationLink`, ported from the M1 sibling repo, used during
registration). This one is the spec's own OTP-verified profile-update pair, a different ABDM endpoint
entirely. Keep both; don't merge or replace either.

### 5 · Update Password — §3.30

`POST /abha/api/v3/phr/app/login/profile/verify`,
`{scope: ["abha-address-profile","password-verify"], authData: {authMethods: ["password"], password:
{abhaAddress, password: <encrypted NEW password>}}}` → confirmed success: `{message: "Password
updated successfully", authResult: "success", users: [{abhaAddress}]}` — real saved Postman example,
matches spec exactly. **No old-password field exists anywhere** — confirmed by directly searching the
whole Postman collection for one; ABDM apparently checks server-side that the new password differs
from the old one (per the spec's own prose), the request only ever carries the new value. One real
form field: the new password.

### Certificate — get this right, this is the part most likely silently wrong

**All five calls above use `settings.phr_certificate_url` (2048-bit, `/phr/app/login/public/certificate`)
— NOT `settings.abdm_profile_certificate_url`.** This matters because the four most recently-built
modules in this project (`aadhaar_enrollment.py`, `mobile_linking.py`, `email_verification.py`,
`abha_card.py`) all correctly use the OTHER certificate — but only because they each hit a genuinely
different URL family (`/enrollment/...` or `/profile/account/...`). Every call in THIS chunk hits
`/phr/app/login/...` — the exact same family mobile OTP login and all five P1-E login methods already
use, and those all correctly use `phr_certificate_url`. Judge by URL family, don't pattern-match on
whichever module you touched most recently.

### Headers — spec and live Postman disagree, send the superset, confirm live

The spec's own header table for Get Profile literally names a header called `X-AUTH-TOKEN` (not
`Authorization`) alongside `X-token`. The other four calls' spec header tables name `Authorization`
(not `X-AUTH-TOKEN`) alongside nothing else. The live Postman collection's saved requests for **all
five** show only `X-token: Bearer {{X-token}}` plus `REQUEST-ID`/`TIMESTAMP` as explicit headers — no
`Authorization` row at all (Postman's own separate `apikey`-type auth block may or may not be standing
in for it — this project already knows that collection mixes `apikey` and gateway-token conventions
inconsistently, and Aayush's standing decision is to keep using the gateway token via `Authorization`
everywhere, not `apikey`). **Send both `Authorization: Bearer <gateway token>` and `X-token: Bearer
<session token>` on every one of these five calls by default** — cheapest safe default, and Get
Profile costs nothing to retry if it turns out one of them is unnecessary. Only chase the literal
`X-AUTH-TOKEN` naming if the Authorization+X-token combination genuinely fails on Get Profile
specifically (that one call is free to retry as many times as needed — no OTP, no state change).

## Build

New module, e.g. `aegle_phr/phr/profile.py` — `get_profile()`, `update_profile()`,
`request_update_mobile_otp()`/`verify_update_mobile_otp()`, `request_update_email_otp()`/
`verify_update_email_otp()`, `update_password()`. Same shape as every prior module (`AbdmResult`
dataclass, `archive()` + redaction, default retry classifier where the call isn't a one-shot OTP
submission). New routes — pick names that don't collide with the already-claimed
`/phr/profile/link-mobile/*` (that's the enrollment-chained flow, different problem, leave it alone),
e.g. `/phr/profile/get`, `/phr/profile/update`, `/phr/profile/update-mobile/request-otp` +
`/verify-otp`, `/phr/profile/update-email/request-otp` + `/verify-otp`, `/phr/profile/update-password`.
New schemas in `schemas.py` following existing naming conventions.

New screen(s) — a `/profile` route (add to `App.tsx`'s nav alongside Login/Register/Create ABHA
Address/Health), showing: photo if available (see item 1), full name, KYC badge (`kycStatus ===
"VERIFIED"` → verified state, otherwise pending/not-verified — match whatever states `kycStatus`
actually returns, don't hardcode just the two seen in examples), ABHA Number, ABHA Address. An edit
affordance revealing every demographic field, enforcing the eKYC-lock rule from item 2, with
mobile/email shown but not directly editable there — instead, separate actions/buttons for "Update
mobile", "Update email", "Update password", each a small OTP (or password) flow of its own, reusing
the request→verify screen shape already established elsewhere in this project (e.g. `OtpLoginScreen`'s
pattern) where that fits, adapted for needing a real logged-in `X-token` rather than a pre-login flow
— your call how much to literally share vs. rebuild small, state what you chose.

**Redaction**: the new mobile/email/password values need the same plaintext-secret treatment given to
every other instance of those fields in this project — assert it (`redaction.contains_any()`), don't
just inspect.

## Explicitly out of scope — flag, don't build

Switch Profile (§3.37/§3.38, the "Switch account" link visible in Aayush's reference screenshot),
Link/De-link ABHA number (§3.31-§3.36), QR code (§3.40), PHR card (§3.41, distinct from the already-built
ABHA card in `abha_card.py`), refresh token (§3.43), logout — all real, all documented, none of them
part of "mobile, email, password" profile updates. Note them as known future chunks in your report,
do not build any of them now.

---

## Verification

**Offline first:**
1. All five request bodies match this prompt's confirmed shapes exactly.
2. Certificate: assert (not inspect) `phr_certificate_url` is what gets used for all five — this is
   the specific mistake the Certificate section exists to prevent.
3. The eKYC-lock rule is unit-testable without a live call — verify offline that `kycStatus:
   "VERIFIED"` locks exactly `firstName`/`middleName`/`lastName`/`dayOfBirth`/`monthOfBirth`/
   `yearOfBirth`/`gender` and nothing else, and that any other `kycStatus` value unlocks them.
4. The "Update" button/action only activates on an actual diff from the fetched baseline — same,
   testable offline.
5. Redaction: assert no plaintext mobile/email/password ends up in `abdm_call_log`.
6. `tsc --noEmit` and `npm run build` clean; `fetch(` still only in `client.ts`; new routes 401
   without `X-Aegle-Key`.

**Then live — Get Profile is free, the rest cost real changes to a real account:**
7. Fetch Get Profile against whichever account is currently logged in (from a prior live-tested login)
   — free, no OTP, no state change. Confirm the real response matches this prompt's field list, and
   settle the photo question (item 1) and the mobile/email-in-updateProfile hypothesis (item 2) against
   what actually comes back.
8. **Stop and ask Aayush before each of the next three** — each changes real account state:
   - Update Profile with a genuine demographic/address edit (pick a field the account's `kycStatus`
     allows changing).
   - Update Mobile (costs a real SMS OTP).
   - Update Email (costs a real email OTP).
   - Update Password — use `chordiaaayush1997@sbx` (already has one set, per this prompt's earlier
     note); confirm the account can still log in with the new password afterward.
9. Add whatever these live runs reveal to `aegle-phr/README.md`'s captured-shapes section — same
   documentation deliverable as every prior chunk (this file is still missing entries for several
   already-built chunks; backfill only if you have the real data in hand from this run, don't go
   hunting for old ones).

If any live step fails, stop and report — don't retry blindly, don't chain into the next live step
without checking in first.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — the five calls above plus the profile page. Flag Switch Profile/Link-
   Delink/QR/PHR-card/refresh/logout rather than building them. Fix bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially the mobile/email-in-updateProfile hypothesis, the photo
   question, and whichever header combination Get Profile actually needed.
8. Do not modify `repo\`. Do not modify `aegle_phr/phr/mobile_linking.py`,
   `email_verification.py`, or `abha_card.py` — they solve different, already-tested problems; this
   chunk adds new modules alongside them, not changes to them.
9. Never print the access key, the client secret, a plaintext OTP, a mobile number, an email address,
   a password, or a live token into your report.
10. `Authorization: Bearer <gateway token>` plus `X-token` on every call in this chunk — no `apikey`
    header, consistent with every prior chunk's decision, even though the live Postman collection's
    own saved requests lean on `apikey` for these specific endpoints.
