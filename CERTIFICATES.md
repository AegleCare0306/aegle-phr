# Encryption certificates — which process uses which, and why

This documents every place `aegle-phr` RSA-encrypts a value before sending it to ABDM, and which of
the two certificate endpoints it must use. Built by reading the actual code (`aegle_phr/phr/*.py`)
directly on 2026-09-01, not from memory — every row below is a real call site, not an inference.

## The two certificates

| | Bit size | Endpoint | Settings field |
|---|---|---|---|
| **PHR certificate** | 2048-bit | `.../abha/api/v3/phr/app/login/public/certificate` | `settings.phr_certificate_url` |
| **Profile certificate** | 4096-bit | `.../abha/api/v3/profile/public/certificate` | `settings.abdm_profile_certificate_url` |

## The rule — and why it's NOT "which URL the call hits"

For a long stretch of this project the working assumption was: judge the certificate by URL family —
`/phr/app/login/*` → PHR cert, `/enrollment/...` and `/profile/account/...` → profile cert. **That
assumption is wrong, and got proven wrong three separate times, live, on three different chunks**:

1. **`abha_address_creation.py` (P1-H)** — a live before/after test. A request to
   `/phr/app/login/request/otp` (the "PHR" URL) encrypted with the PHR cert returned a raw Java
   range-exception (`"Range [6, 0) out of bounds for length 0"`) — the signature of ABDM receiving
   the ciphertext but decrypting it into garbage. Switching the SAME call to the profile cert turned
   that into a real, specific business answer (`"User not found"`). Same URL, different cert needed.
2. **`profile_link.py` (P1-N)** — Link ABHA Number's request/verify steps, also on the `/phr/app/
   login/profile/...` URL, hit the identical problem and needed the identical fix.
3. **`login.py` (fixed 2026-09-01)** — this is the fix Aayush just made: three of the seven login
   methods (ABHA-Number-via-Aadhaar-OTP, raw-Aadhaar-Number-OTP, ABHA-Number-via-Mobile-OTP) were
   stuck on a long-flagged "Invalid LoginId" error. Root cause was the same bug, now fixed.

**The actual rule, confirmed all three times**: certificate choice tracks the request's **`scope`**
field, not the URL. Specifically:

- Any call whose `scope` list contains **`"abha-login"`** → **profile certificate** (4096-bit).
- Every other scope family used by this app — `"abha-address-login"`, `"abha-address-enroll"`,
  `"abha-address-profile"` — → **PHR certificate** (2048-bit).

`"abha-login"` is ABDM's identity/profile-service scope; the other three are all address-service
scopes. That's the actual boundary — it happens to have lined up with the URL-family heuristic for
most calls (which is why that heuristic looked right for a while), but the `"abha-login"` scope
family breaks it, on three different URLs, independently, every time it's come up.

A second, separate category exists alongside this: the older, **M1-ported endpoints**
(`/enrollment/...` and `/profile/account/...` — a structurally different API surface from the PHR
spec's own `/phr/app/login/...` family, carried over from the existing HIP/HIU repo's own Aadhaar
e-KYC flow). These don't use the `scope`-list convention at all and are simply, always, on the
profile certificate — not because of a scope value, just because that's the API family they belong
to.

## Full table — every encrypting call in this app

**PHR-native family (`/phr/app/login/...`) — certificate follows `scope`:**

| Route | Module / function | Scope | Field(s) encrypted | Certificate |
|---|---|---|---|---|
| `/phr/enrollment/request-otp` | `enrollment.request_otp()` | `abha-address-enroll` | mobile (as loginId) | PHR (2048) |
| `/phr/enrollment/verify-otp` | `enrollment.verify_otp()` | `abha-address-enroll` | OTP value | PHR (2048) |
| `/phr/enrollment/enrol` | `enrollment.enrol()` | `abha-address-enroll` | mobile, email, password | PHR (2048) |
| `/phr/login/verify` (password) | `login.verify_password()` | `abha-address-login` | password | PHR (2048) |
| `/phr/login/request-otp` / `verify-otp` (mobile) | `login._request_otp_login()` / `_verify_otp_login()` | `abha-address-login` | mobile / OTP value | PHR (2048) |
| `/phr/login/abha-address-via-mobile/*` | same, mobile-channel ABHA-Address login | `abha-address-login` | mobile / OTP value | PHR (2048) |
| `/phr/login/abha-address-via-email/*` | same, email-channel ABHA-Address login | `abha-address-login` | email / OTP value | PHR (2048) |
| `/phr/login/abha-number-via-aadhaar/*` | same, ABHA-Number via Aadhaar OTP | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** — fixed 2026-09-01 |
| `/phr/login/aadhaar-number/*` | same, raw Aadhaar Number login | **`abha-login`** | Aadhaar number / OTP value | **Profile (4096)** — fixed 2026-09-01 |
| `/phr/login/abha-number-via-mobile/*` | same, ABHA-Number via Mobile OTP | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** — fixed 2026-09-01 |
| `/phr/login/search`, `/phr/login/verify-user` | `login.search_user()` / `verify_user()` | — | *(nothing encrypted — plaintext lookup / token exchange)* | N/A |
| `/phr/profile/update-mobile/*` | `profile.request_update_mobile_otp()` / verify | `abha-address-profile` | mobile / OTP value | PHR (2048) |
| `/phr/profile/update-email/*` | `profile.request_update_email_otp()` / verify | `abha-address-profile` | email / OTP value | PHR (2048) |
| `/phr/profile/update-password` | `profile.update_password()` | `abha-address-profile` | new password | PHR (2048) |
| `/phr/profile/get`, `/phr/profile/update` | `profile.get_profile()` / `update_profile()` | — | *(nothing encrypted — Update Profile sends mobile/email plaintext, echoed unchanged from Get Profile)* | N/A |
| `/phr/profile/link/mobile/*` | `profile_link.py`, Link ABHA Number via Mobile OTP | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** |
| `/phr/profile/link/aadhaar/*` | `profile_link.py`, Link ABHA Number via Aadhaar OTP | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** |
| `/phr/profile/link/process` | `profile_link.py`, LINK/DELINK finalize | — | *(nothing encrypted — action + transactionId, plaintext)* | N/A |
| `/phr/profile/switch/request`, `/switch/verify` | `profile_link.py`, Switch Profile | — | *(nothing encrypted — abhaAddress + txnId, plaintext)* | N/A |
| `/phr/profile/qr-code`, `/phr/profile/phr-card` | `profile_link.py` | — | *(nothing encrypted — GET, X-Token only)* | N/A |
| `/phr/profile/refresh-token` | `profile_link.py` | — | *(nothing encrypted — R-Token header only)* | N/A |
| `/phr/abha-address/request-otp-aadhaar`, `verify-otp-aadhaar` | `abha_address_creation.py`, ABHA-Address creation for an existing ABHA Number, Aadhaar-OTP variant | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** — the original P1-H fix |
| `/phr/abha-address/request-otp-mobile`, `verify-otp-mobile` | `abha_address_creation.py`, mobile-OTP variant | **`abha-login`** | ABHA number / OTP value | **Profile (4096)** |

**M1-ported legacy family (`/enrollment/...`, `/profile/account/...`) — always the profile certificate, no scope branching:**

| Route | Module / function | Field(s) encrypted | Certificate |
|---|---|---|---|
| `/phr/aadhaar-enrollment/request-otp` | `aadhaar_enrollment.request_otp()` | Aadhaar number (as loginId) | Profile (4096) |
| `/phr/aadhaar-enrollment/enrol` | `aadhaar_enrollment.enrol_by_aadhaar()` | OTP value | Profile (4096) |
| `/phr/aadhaar-enrollment/create-address`, `/suggestions` | `aadhaar_enrollment.create_abha_address()` / `get_address_suggestions()` | *(nothing encrypted — chained off the existing transaction, plaintext txnId + address)* | N/A |
| `/phr/profile/link-mobile/request-otp`, `verify-otp` | `mobile_linking.py` | mobile / OTP value | Profile (4096) |
| `/phr/aadhaar-enrollment/abha-card` | `abha_card.py` | *(nothing encrypted — fetch only, X-token)* | N/A |
| `/phr/profile/request-email-verification-link` | `email_verification.py` | email (as loginId) | Profile (4096) |

## Quick reference — the short version

- **PHR certificate (2048-bit)**: mobile enrollment, password/mobile/email login and profile-update
  OTP flows — anything whose scope is `abha-address-*`.
- **Profile certificate (4096-bit)**: anything whose scope is `abha-login` (ABHA-Number login,
  Aadhaar-Number login, Link/De-link ABHA Number, ABHA-Address-for-existing-number creation) — PLUS
  the entire M1-ported legacy family (`/enrollment/...`, `/profile/account/...`), unconditionally.
- **No certificate at all**: any call that doesn't RSA-encrypt anything — plain fetches (Get Profile,
  QR Code, PHR Card), plaintext-only bodies (Update Profile, Link/De-link's finalize step, Switch
  Profile), and token exchanges (`verify-user`, Refresh Token).

## Where this lives in the code

Every module's own file banner (`aegle_phr/phr/*.py`) carries this same reasoning in more detail,
scoped to that module — this file exists so the full cross-module picture is in one place instead of
scattered across nine separate banners. If a new PHR endpoint is added later, check its `scope` value
against the rule above before assuming either certificate.
