# Claude Code prompt — P1-F: real Aadhaar-based ABHA registration

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.** This one touches real Aadhaar data and a new
> shared-package boundary — worth the extra care extended thinking gives, same as every prior
> live-sandbox chunk.

> **P1-E (the five remaining login methods) is on hold** — none of the non-mobile login methods are
> working yet and Aayush is investigating separately. Don't touch anything from that prompt or that
> investigation. This is a different, self-contained chunk.

---

Two changes, requested together because the second depends on the first's output:

1. **Add real Aadhaar-based ABHA Number creation** — the flow already built and live-tested in the
   sibling `repo/` as part of M1 (not part of the PHR spec at all — a different, older ABDM API
   surface). Bring that capability into this project.
2. **Rework PHR registration** (`aegle_phr/phr/enrollment.py`'s `enrol()`, currently reached via
   `/enroll` in the test UI): rename it to "Register" in every user-facing place, and remove every
   manual demographic field (`firstName`, `middleName`, `lastName`, DOB, gender, email, address,
   state, district, pincode) — once change 1 runs first, that data comes back from Aadhaar e-KYC
   and should be used directly, never re-typed. Only `password` (and optionally a custom ABHA
   address, if Aayush wants to keep that as a choice rather than accepting whatever gets
   auto-assigned) remain real form fields.

## New evidence, 2026-08-30 — pulled live from Aayush's own Postman account, not just the uploaded file

Aayush's actual Postman workspace (connected directly via the Postman API, not the earlier uploaded
export) has a collection literally called **"PHR"**, more current than the M1 export this prompt
originally cited. It has a saved, real example response for `enrollment/enrol/byAadhaar` that
resolves several things this prompt was previously asking you to confirm from scratch:

```json
{
  "message": "Account created successfully",
  "txnId": "...",
  "tokens": { "token": "...", "expiresIn": 1800, "refreshToken": "...", "refreshExpiresIn": 1296000 },
  "ABHAProfile": {
    "firstName": "Username", "middleName": "Kailas", "lastName": "Shelke",
    "dob": "26-06-1999", "gender": "M", "photo": "<base64 face photo>",
    "mobile": "******0903", "phrAddress": ["9175614088XXXX@sbx"],
    "address": "LOHARA, AT POST LOHARA TQ PACHORA DIST JALGAON, ...",
    "districtCode": "478", "stateCode": "27", "pinCode": "424201",
    "abhaType": "STANDARD", "stateName": "MAHARASHTRA", "districtName": "JALGAON",
    "ABHANumber": "91-7561-4088-XXXX", "abhaStatus": "ACTIVE"
  },
  "isNew": true
}
```

Treat this as strong prior evidence, not gospel — it's a saved example from Aayush's own testing,
not something this project has independently reproduced yet. Still capture and report the real live
response per the Verification section below, but you're now confirming a specific known shape rather
than exploring blind. Three things this changes about how you should build change 2:

1. **Full demographics are confirmed present** under `ABHAProfile` — `firstName`, `middleName`,
   `lastName`, `dob` (a single string, `DD-MM-YYYY` — split it into `enrol`'s separate
   `dayOfBirth`/`monthOfBirth`/`yearOfBirth`, and confirm the day/month order live rather than
   assuming, since a silently-swapped day/month is exactly the kind of bug that wouldn't be obvious
   from a 200 response), `gender`, `mobile`, `address`, `stateName`/`stateCode`,
   `districtName`/`districtCode`, `pinCode`. Map these directly into `enrol`'s `phrDetails` — this
   was previously "confirm the mapping live," now it's "confirm this specific mapping still holds."
2. **This response already includes a full session token** (`tokens.token`, `expiresIn: 1800`, real
   `refreshToken`) **and an already-assigned ABHA Address** (`ABHAProfile.phrAddress`) — this is NOT
   the short-lived transfer-token shape seen elsewhere in this project (that's `expiresIn: 300`, no
   refreshToken). If this holds live, **`enrol/byAadhaar` alone may already produce a fully usable
   account** — Number, Address, and a real session — before PHR's own `enrol` is ever called.
3. **This directly changes what "investigate before building" means for change 2** — see the
   rewritten section below.

## Authentication — settled, use the gateway token everywhere in this chunk

The same Postman collection's request templates mostly use a Postman `apikey`-type header instead of
`Authorization: Bearer <gateway token>` for PHR Login/Profile calls. **Don't follow that.** Aayush's
call: stick with `Authorization: Bearer <gateway token>` throughout this chunk, exactly like every
other call in this project (`repo/server/abha.py`'s own `request_otp()`/`enroll_by_aadhaar()` already
do this correctly). Do not introduce an `apikey` header anywhere. This isn't something to test both
ways — it's decided.

## A ground-rule change for this chunk only, stated up front

Every prior prompt in this project has said "do not modify `repo\` or `aegle-abdm-core\`." That
still holds for `repo\` — it stays **fully read-only reference material**, never edited. But this
chunk needs new code added to **`aegle-abdm-core`**, not `aegle-phr` — this is genuinely shared ABDM
logic (Aadhaar e-KYC ABHA-Number creation has nothing to do with PHR specifically), and
`aegle-abdm-core` is exactly the package this project already decided shared code belongs in
(Aayush's decision 3, 2026-08-27: "Shared code → installable `aegle-abdm-core`, both repos via
pip"). **Add new modules/functions to `aegle-abdm-core`. Do not modify any existing P0-A file's
behavior** — this is additive only. `repo/server/abha.py` keeps working exactly as it does today;
nothing there changes.

## Change 1 — port the Aadhaar flow into `aegle-abdm-core`

**Primary source of truth: `repo/server/abha.py`'s `request_otp()` and `enroll_by_aadhaar()`,
already tested against the real sandbox (tracker case M1-16, confirmed live 2026-08-17).** Read
these directly and port their behavior faithfully — don't reimplement from scratch or from memory of
how similar endpoints work elsewhere in this project.

**Secondary reference, two Postman sources**: (a) the file Aayush originally uploaded
(`postman_collection_m1_e66da1f265`) — be aware it documents an **older API generation**, its
`RegistrationWithAadhaar` folder hits `/v1/registration/aadhaar/...` and
`/v2/registration/aadhaar/checkAndGenerateMobileOTP`, while `repo/server/abha.py`'s actual, tested
implementation hits `/v3/enrollment/enrol/byAadhaar` — a different, newer endpoint entirely; (b) the
live "PHR" collection in Aayush's own Postman workspace (pulled directly 2026-08-30, see the new
evidence section above) — newer and more relevant, has the real `enrol/byAadhaar` example response
quoted above. Where any of these disagree with `repo/server/abha.py`, **`repo/server/abha.py`
wins for the request shape** — it's the implementation that's actually been run against the sandbox
and had real bugs found and fixed (see its wrong-OTP-signature handling below). The "PHR" collection's
saved *response* is the best evidence available for what comes back, precisely because the request
shape isn't in question there — only the response shape was previously unconfirmed.

### The two-call flow, exactly as `repo/server/abha.py` implements it

**1. Request OTP** — reuses the same generic `request_otp(action, scope, login_hint, login_id,
otp_system, txn_id=None, x_token=None)` shape already familiar from this project, called with:
`action="enrollment"`, `scope=["abha-enrol"]`, `login_hint="aadhaar"`,
`login_id=<encrypted Aadhaar number>`, `otp_system="aadhaar"`. URL:
`{ABHA_BASE_URL}/enrollment/request/otp`.

**2. Enroll by Aadhaar** — `POST {ABHA_BASE_URL}/enrollment/enrol/byAadhaar`:
```json
{ "authData": { "authMethods": ["otp"],
                "otp": { "timeStamp": "<ISO8601>", "txnId": "<from step 1>",
                         "otpValue": "<encrypted OTP>", "mobile": "<mobile, PLAIN, NOT encrypted>" } },
  "consent": { "code": "abha-enrollment", "version": "1.4" } }
```
**No name/DOB/gender/address fields anywhere in this request** — confirms Aayush's premise directly:
this endpoint doesn't need them, because ABDM already has them from Aadhaar's own e-KYC data.

**Two things to carry over exactly, not rediscover the hard way:**

- **The mobile number is sent in plaintext in this call, unlike every other mobile field in this
  project.** `repo/server/abha.py`'s own comment confirms this deliberately ("This is the one field
  deliberately NOT encrypted -- confirmed from the documented request body"). Do not encrypt it here
  even though the instinct from every other flow in this codebase would be to.
- **Two confirmed wrong-OTP response signatures**, both already found live and worth porting rather
  than rediscovering: (a) HTTP 400 with `{"mobile": "Invalid Mobile Number", ...}` — ABDM's own
  field label is misleading here, the actual cause is the OTP, not the mobile; (b) HTTP 422 with
  `{"error": {"code": "ABDM-1204", "message": "UIDAI Error code : 400 : OTP validation failed"}}`.
  Both mean "wrong OTP," not "bad mobile number" or an unrelated UIDAI failure. See
  `repo/tools/m1_test_suite/flows/enrollment.py`'s `_WRONG_OTP_SIGNATURE`/
  `_WRONG_OTP_SIGNATURE_ABDM_1204` for the exact matching logic — port the same classify-don't-guess
  approach (a signature that doesn't match either shape gets the full raw dump, not a
  guessed-friendly message, and is not retried).

### Certificate — this is the part most likely to be gotten wrong silently

**This flow encrypts against the PROFILE certificate, not the PHR certificate.**
`repo/tools/m1_test_suite/common.py`'s `encrypt()` calls `server/crypto.py`'s
`get_public_certificate()` with no URL override, which defaults to
`{ABHA_BASE_URL}/profile/public/certificate` — the **4096-bit** key from this project's own
HARD-WON FACT, not the 2048-bit `phr_certificate_url` every other `aegle-phr` call uses. Using the
wrong certificate here produces ciphertext ABDM silently can't decrypt — not an obvious error, just
a mysterious failure. `abdm_core.rsa_crypto.get_public_certificate(certificate_url)` is already
per-URL cached exactly for this reason (P0-A's design, load-bearing, do not collapse it) — just call
it with the right URL. Add a new field to `aegle_phr/settings.py`'s `Settings`, following the exact
pattern `phr_certificate_url` already uses (derived default if not set explicitly):
```python
abdm_profile_certificate_url: str = ""
# derived: f"{abdm_abha_base_url}/profile/public/certificate" if not set
```

### Response — confirmed shape from live evidence, still verify it holds for real

The new-evidence section above already gives you the expected shape from a real saved example:
`message`, `txnId`, `tokens` (a FULL session token — `expiresIn: 1800` + `refreshToken`, not the
short-lived transfer-token shape), `ABHAProfile` (all the demographic fields, `dob` as one string),
`isNew`. `repo/tools/m1_test_suite/flows/enrollment.py`'s own `_print_outcome()` only ever extracted
five things from this same response (`isNew`, `mobileVerified`, `mobile`, an ABHA Number under
either `ABHANumber`/`healthIdNumber`, an ABHA Address under either `preferredAbhaAddress`/
`phrAddress`) because that's all its CLI purpose needed — not evidence the rest wasn't there, and
the Postman example now confirms it was. **Still capture and report the complete raw response body
from your own live test** — confirming a specific known shape is much cheaper than exploring blind,
but this project has been burned before by an example not quite matching live reality (the T-token
name itself was "in the spec" too, just easy to miss). If your live result doesn't match the shape
above, report the actual difference plainly rather than silently reconciling it.

## Change 2 — rework registration to use Aadhaar's data instead of a form

**Test the simplest hypothesis first, given the new evidence above**: if `enrol/byAadhaar`'s response
really does include a full session token (`expiresIn: 1800` + `refreshToken`) and an already-assigned
`ABHAProfile.phrAddress`, **the account may already be fully created and usable after change 1's
single call — before PHR's own `/phr/app/enrollment/enrol` is ever invoked.** Test this directly: after
a live `enrol/byAadhaar` call, try logging into the resulting account (e.g. via the already-working
mobile-OTP or password login from prior chunks — password login won't work yet since no password was
ever set, so mobile-OTP is the more useful check here) using the address/number that came back. If
that works, PHR's own `enrol` step becomes **optional** — needed only if Aayush wants to (a) set a
password (this flow never collects one, so password-based login stays unavailable until one is set
some other way), or (b) choose a custom ABHA address instead of the auto-assigned one. Build for
that: change 1's flow is the primary path and can stand alone; change 2's reworked `enrol`/"Register"
becomes an optional follow-up specifically for setting a password (and optionally a custom address),
not a mandatory second step to get a working account.

**If PHR's `enrol` IS still needed** (either because the hypothesis above doesn't hold, or because
Aayush wants the password/custom-address step regardless): it requires a `txnId` from a
**successfully verified OTP transaction** — in the currently-built flow, that's PHR's own
`/phr/app/enrollment/request/otp` + `/verify` (mobile-based, already built in
`aegle_phr/phr/enrollment.py`). The Aadhaar flow from change 1 opens its **own, separate** ABDM
transaction (`action="enrollment"`, different scope) — it is not obviously the same `txnId` space.
**Test directly whether `enrol` will accept the Aadhaar flow's `txnId`** (cheaper — one fewer OTP if
it works) before assuming it won't; Aayush's own "PHR" Postman collection's "Create ABHA Address
Flow" folder structure suggests each such flow runs its own dedicated OTP request/verify immediately
before its `Enroll ABHA Address` call, which is evidence (not proof) that a fresh, separately-scoped
transaction is what `enrol` actually wants — but confirm it live rather than trusting that inference.
If ABDM rejects the Aadhaar `txnId` (an "Invalid Transaction Id" style 400), fall back to the
two-transaction design: Aadhaar OTP request/verify first (gets identity data + confirms the mobile),
then PHR's own existing mobile request-otp/verify (same mobile, already confirmed by step 1 —
pre-fill it, don't re-ask, but the OTP itself is still a separate ABDM transaction and still needs to
actually be requested and entered) to get the `txnId` `enrol` actually wants. **State plainly in your
report which of these turned out to be true** — whether `enrol` was needed at all, and if so whether
it cost one real OTP or two, since that's a real cost Aayush should know explicitly.

**Whenever `enrol` IS called**: build its `phrDetails` payload from the Aadhaar response's
`ABHAProfile` fields directly — `firstName`, `middleName`, `lastName`, split `dob` (a single
`DD-MM-YYYY` string, confirm the day/month order live) into `dayOfBirth`/`monthOfBirth`/
`yearOfBirth`, `gender`, `address`, `stateName`/`stateCode`, `districtName`/`districtCode`,
`pinCode` — `email` isn't in the confirmed `ABHAProfile` shape above, leave it blank/omitted unless
your live test shows otherwise. The **only** real form inputs for registration become:
- `password` (required, `enrol` needs one regardless of how the identity was established).
- An optional custom ABHA address, if you want to preserve letting Aayush choose one instead of
  automatically accepting whatever `preferredAbhaAddress` the Aadhaar step returned — reuse the
  existing `suggestion`/`address-exists` machinery from P1-A for this rather than building new
  plumbing, if you keep it. If you drop it and just use the auto-assigned address, say so plainly —
  this is a real UX choice, not an obvious default.

**Rename "enrol"/"Enrollment" to "Register"/"Registration" everywhere user-facing** — screen titles,
button text, any visible copy. Leave backend/ABDM-facing naming alone (the actual API is still
called `enrol`, the Python function names can stay if renaming them is more churn than value — your
call, but state what you chose). The `/enroll` route can keep its URL or move to `/register` — minor
either way, just be consistent and say which you picked.

## Reuse — nothing else changes

- `abdm_call_log` archiving, `redaction.py` — extend the same way every prior chunk has: check this
  new endpoint's actual live response for anything plaintext-sensitive before assuming existing
  rules cover it. Aadhaar numbers specifically need the same treatment already given to mobile
  numbers and passwords — plaintext-unsafe, redact if found anywhere in a response.
- Session storage, retry policy (no retry on OTP request steps, same as every OTP flow in this
  project) — unchanged.
- `verify_user()`, the login flows — untouched, out of scope for this chunk.

---

## Verification

**Offline first:**
1. New `aegle-abdm-core` module's request bodies match `repo/server/abha.py` field-by-field,
   including the plaintext-mobile exception and the exact consent code/version.
2. Certificate: assert (not just inspect) that this flow's encryption calls
   `get_public_certificate()` with the profile URL, not `phr_certificate_url`.
3. Redaction: assert no plaintext Aadhaar number or mobile number ends up in `abdm_call_log` for
   this flow, same proof technique as every prior chunk (`redaction.contains_any()`).
4. `enrol()`'s payload, once reworked, contains zero hardcoded/placeholder demographic values — every
   field traces to either the Aadhaar response or the password form input.
5. `tsc --noEmit` and `npm run build` clean; `fetch(` still only in `client.ts`.
6. Confirm `repo/` has zero diffs from this chunk (`git status`/`git diff --stat` inside `repo/`
   before and after) — this is the one prompt in the project explicitly allowed to touch
   `aegle-abdm-core`, but `repo/` stays exactly as untouched as always.

**Then live — this costs at least one real Aadhaar OTP, possibly two or three depending on which
hypotheses hold:**
7. Stop and ask Aayush for a real Aadhaar number, the mobile to receive the OTP on, and to read back
   the OTP — same one-shot rule as every prior live run: request once, verify once, don't loop on
   failure without asking first.
8. Report the full raw `enroll_by_aadhaar`-equivalent response body (redacting only genuinely
   sensitive values) — this is the chunk's real documentation deliverable, confirming or correcting
   the shape already given in the new-evidence section above. Add it to `aegle-phr/README.md`'s
   captured-shapes section.
9. Test whether the account is already usable at this point (see "test the simplest hypothesis
   first" above) — try an existing login method against it before deciding `enrol` is still needed.
10. If `enrol`/"Register" is still exercised (for password-setting and/or a custom address), walk it
    through to completion once with a real password, and confirm the created/updated account can
    actually log in afterward the same way.

If the live run fails at any step, stop and report — don't retry blindly, don't burn a second
Aadhaar OTP chasing the same failure without checking in first.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — these two changes only. Flag anything else you spot, don't fix it. Fix
   bugs you introduce yourself. P1-E is on hold — don't touch it or resume it.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially the txnId-reuse hypothesis, and whatever demographic
   field-name mapping you find between the Aadhaar response and `enrol`'s expected `phrDetails`.
8. **Do not modify `repo\`** — read-only reference only. `aegle-abdm-core\` may be **added to**
   (new modules/functions) but not have any existing behavior changed — this is the one exception to
   this project's usual "don't touch core" rule, scoped narrowly to additive changes for this chunk.
9. Never print the access key, the client secret, a plaintext Aadhaar number, a plaintext OTP, a
   mobile number, or a live token into your report.
10. `Authorization: Bearer <gateway token>` everywhere in this chunk — decided, not a design choice.
    Do not introduce an `apikey` header, even though Aayush's own Postman collection uses one for
    similar calls elsewhere.
