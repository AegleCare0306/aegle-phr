# Claude Code prompt — P1-A: ABHA address registration via mobile number

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

Build the **first real ABDM flow** in the PHR app: registering a new ABHA address using a mobile number, driven end to end from the test UI.

This is one of three registration paths. The other two (via ABHA number + Aadhaar OTP, and via ABHA number + mobile OTP) come next and reuse almost all of this. Build only the mobile path.

## Why this chunk is shaped the way it is

Every previous chunk was plumbing. This one is the first vertical slice that touches a real patient identity flow, so it proves several things at once: RSA encryption against the PHR certificate, ABDM's scope model, the `txnId` chain across calls, and whether our request shapes are actually right.

Two constraints follow from that, and both matter more than the code.

### ⚠️ Every OTP request sends a real SMS and counts toward a lockout

Requesting an OTP triggers a real message to a real phone. ABDM rate-limits this hard: `ABDM-1100` — *"You have requested multiple OTPs or exceeded maximum number of attempts for OTP match in this transaction. Please try again in 30 minutes."* `ABDM-1027` blocks the client for 24 hours.

Therefore: **do not script retries, loops, or repeated OTP requests during verification.** Run the happy path once, with me supplying the number and reading the OTP. Everything else gets tested against mocks. If a run fails partway, stop and tell me rather than immediately re-requesting.

### ⚠️ Several success response shapes are NOT documented

The spec gives complete request bodies but leaves the "Response Body" section **empty** for `/enrollment/verify`, `/enrollment/suggestion`, and `/enrollment/enrol`. I have checked; this is a gap in the document, not something you're missing.

So: **do not invent response models.** Return and store the raw JSON, log it in full, and let the first real sandbox run tell us the shape. Write Pydantic response models only for what is actually documented. Where you must reference a field that isn't documented, mark it clearly in a comment as unconfirmed.

Capturing those shapes is a real deliverable of this chunk — as valuable as the code.

---

## The flow — five ABDM calls

Base URL `settings.abdm_abha_base_url`. All five take `REQUEST-ID`, `TIMESTAMP`, and `Authorization: Bearer <gateway token>` (from `abdm_core.session.get_gateway_token()`).

### 1. Request OTP — `POST /phr/app/enrollment/request/otp`
```json
{ "scope": ["abha-address-enroll", "mobile-verify"],
  "loginHint": "mobile-number",
  "loginId": "<RSA-encrypted mobile>",
  "otpSystem": "abdm" }
```
Documented response: `200` with `{ "txnId": "...", "message": "OTP is sent to Mobile number ending with ******2425" }`

### 2. Verify OTP — `POST /phr/app/enrollment/verify`
```json
{ "scope": ["abha-address-enroll", "mobile-verify"],
  "authData": { "authMethods": ["otp"],
                "otp": { "txnId": "<txnId>", "otpValue": "<RSA-encrypted OTP>" } } }
```
Response shape **undocumented**. The prose says it returns a success message plus any ABHA address already linked to that mobile — capture what actually arrives.

### 3. Address suggestions — `POST /phr/app/enrollment/suggestion`
```json
{ "txnId": "...", "firstName": "...", "lastName": "...",
  "dayOfBirth": "14", "monthOfBirth": "11", "yearOfBirth": "1998" }
```
The spec lists `email` as required in the parameter table but **omits it from the example body** — a contradiction in the document. Send it only if present, and record what happens.
Response shape **undocumented**.

### 4. Address availability — `GET /phr/app/enrollment/isExists?abhaAddress=johndoe@sbx`
Returns a **bare `true`** — not an object. Handle a non-JSON-object body.

### 5. Enrol — `POST /phr/app/enrollment/enrol`
```json
{ "txnId": "...",
  "phrDetails": { "mobile": "<encrypted>", "firstName": "", "middleName": "", "lastName": "",
                  "dayOfBirth": "", "monthOfBirth": "", "yearOfBirth": "", "gender": "M",
                  "email": "", "address": "", "stateName": "", "stateCode": "",
                  "districtName": "", "districtCode": "", "pinCode": "",
                  "abhaAddress": "johndoe@sbx", "password": "<encrypted>" } }
```
`ABHANumber` and `profilePhoto` appear in one example and not others — treat both as optional.
Response shape **undocumented**. In particular, **whether this returns the patient's `X-token` is unknown.** If it does, capture it; if it doesn't, say so plainly — that determines whether P2 needs a separate login step after registering.

## Encryption

`mobile`, `otpValue` and `password` are RSA-encrypted. Use what already exists and is proven:

```python
from abdm_core.rsa_crypto import get_public_certificate, encrypt_value
get_public_certificate(settings.phr_certificate_url)   # NOT the profile endpoint
```

The PHR certificate endpoint serves a **2048-bit** key; the other endpoint in the sibling repo serves a different **4096-bit** key. Using the wrong one produces ciphertext ABDM cannot decrypt, and the failure surfaces later as a generic error. `settings.phr_certificate_url` is already correct — just don't hardcode anything.

## Backend structure

New `aegle_phr/phr/enrollment.py` — one function per ABDM call, each returning the parsed body plus the status code. Wrap outbound calls in `abdm_core.http.call_with_retry`, matching how the sibling repo does it. **Do not retry OTP requests** — pass a classifier that treats nothing as transient for call 1, or skip the wrapper there entirely and say which you chose.

New routes on the **app-API router** (so they inherit the `X-Aegle-Key` gate — never the callback router):

```
POST /phr/enrollment/request-otp
POST /phr/enrollment/verify-otp
POST /phr/enrollment/suggestions
GET  /phr/enrollment/address-available
POST /phr/enrollment/enrol
```

The UI holds the `txnId` and passes it back on each step. No server-side state machine — this is a harness, keep it flat.

### Archive every ABDM call, with plaintext redacted

Add an `abdm_call_log` table (Alembic migration, same style as `callback_log`): timestamp, our route, ABDM URL, request body, response status, response body, duration. This is how we recover the undocumented response shapes after a run.

**Redact before storing.** The plaintext mobile number, OTP, and password arrive at our backend from the UI. Never write those to the table, the logs, or your report. The RSA-encrypted values are opaque and safe to store — store those.

## UI

One new **Register** screen in `testui/`, following the add-a-screen recipe in its README. A simple stepper:

1. Mobile number → Request OTP
2. OTP → Verify
3. Name, date of birth, gender, optional address fields → Get suggestions
4. Pick a suggested address or type one → check availability → set password → Enrol
5. Result — show the raw enrol response

Keep it plain. No component library, no validation library. `txnId` is held in React state and shown on screen (it is useful when debugging against ABDM). Every call goes through the existing `client.ts`, so the Console panel shows all of it for free — **do not add any `fetch()` outside `client.ts`**.

Password and OTP inputs are `type="password"`. Do not put either in `localStorage`.

---

## Verification

**Offline, mocked — all of this first:**

1. Request bodies for all five calls match the shapes above exactly. Assert field-by-field against a mocked transport; a typo'd key is the single most likely failure and costs a real OTP to discover.
2. `encrypt_value` is called with the certificate from `settings.phr_certificate_url`, not any other URL.
3. `isExists` handles a bare `true` body without raising.
4. Redaction works: drive a call with a known plaintext mobile/OTP/password and assert none of those strings appear anywhere in `abdm_call_log`.
5. All new routes are on the gated router — each returns 401 without `X-Aegle-Key`. The six callback routes still return their normal responses without it.
6. Alembic migration applies cleanly on the running Postgres; show the real `information_schema` output.
7. Frontend: `tsc --noEmit` and `npm run build` clean; `grep` confirms `fetch(` still only in `client.ts`.

**Then one live sandbox run — once.**

8. Stop and ask me for a mobile number before making any live call. I will supply it and read back the OTP. Walk the full path once: request → verify → suggestions → availability → enrol.

Then report, verbatim, the **actual response bodies** for `verify`, `suggestion` and `enrol`, with any token or identifier redacted but its presence and shape described. Explicitly answer:

- Does `enrol` return an `X-token` or any session token? If yes, what is it called?
- What does `verify` return when the mobile has no existing ABHA address?
- Did `suggestion` accept the request without `email`?

If the live run fails, **stop and report** — do not re-request an OTP.

Delete verification scripts once they pass. Add a short "captured response shapes" section to `aegle-phr/README.md` recording what we learned, marked as observed-once rather than specified.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — only the mobile registration path. Flag anything outside it, don't fix it. Fix bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — every undocumented response shape must be labelled as such in code comments and in your report.
8. Do not modify `repo\` or `aegle-abdm-core\`.
9. Never print the access key, the client secret, a plaintext OTP, a mobile number, or a password into your report.
