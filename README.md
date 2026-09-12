# aegle-phr

The patient-facing (PHR) side of Aegle's ABDM integration.

Scaffold (configuration, database, callback plumbing, the mount seam) plus
the first real ABDM flow: **ABHA address registration via mobile number**
(P1-A). The other two registration paths — via ABHA number + Aadhaar OTP,
and via ABHA number + mobile OTP — come next and reuse most of it.

Shared ABDM plumbing (gateway sessions, retries, RSA/Fidelius crypto,
callback JWT verification, logging) lives in the sibling
[`aegle-abdm-core`](../aegle-abdm-core) package and is consumed, not
duplicated.

## The one thing to understand first

**This is a mountable sub-app, not a standalone server.**

The PHR will eventually run *in the same process* as the existing ABDM
backend — one client ID, one callback URL, one ngrok host, so one place for
ABDM callbacks to land. Everything is built for that:

```python
from aegle_phr.bootstrap import bootstrap
from aegle_phr.api import build_router

bootstrap(settings)
app.include_router(build_router(settings))
```

That is the whole integration. Which means these are hard rules, not style
preferences:

- **No module-level side effects anywhere in `aegle_phr`.** No engine at
  import, no `configure()` at import, no path resolution, no directory
  creation, no `Settings()` instantiated. All of it would otherwise fire
  inside the *host's* import graph, before the host has configured itself.
- **All setup lives in `bootstrap()`, and it is idempotent.** A host may
  have bootstrapped already; a second call must not build a second engine.
- **No global state in the router, no `@app.on_event` handlers.** A fresh
  router per `build_router()` call.
- **Every path is fully qualified** (`/api/v3/...`, `/phr/...`). Nothing
  relies on a mount prefix.
- **Every route handler is a plain `def`, never `async def`.** Everything
  downstream blocks (`requests` in `abdm_core`, sync SQLAlchemy here), so
  FastAPI's threadpool is the correct place for it. The existing backend
  already shipped and fixed an event-loop stall of exactly this shape
  (commit `6a1d748`); once both apps share a process, the blast radius is
  shared too.

## Dev startup

```bash
docker compose up -d && alembic upgrade head && python -m aegle_phr
```

That brings up Postgres 16 on **host port 5433** (not 5432 — a silent
collision with an existing local Postgres would connect the app to the
wrong database), applies migrations, and serves on **port 8001** (the
existing backend owns 8000).

First-time setup:

```bash
cp .env.example .env    # then fill in real values
pip install -e ../aegle-abdm-core
pip install -e ".[dev]"
```

`.env` holds the real ABDM client secret and is gitignored. `.env.example`
has placeholders only. The existing backend hardcodes its credentials in
`server/config.py` and consequently has a real secret in its git history —
this repo does not repeat that.

## Standalone vs. mounted

| | Standalone (dev) | Mounted (production) |
|---|---|---|
| Entry point | `python -m aegle_phr` | host app's own |
| App object | `aegle_phr.app.create_app()` | the host's `FastAPI()` |
| Routes | `create_app()` includes `build_router()` | `app.include_router(build_router(settings))` |
| CORS | applied by `create_app()` | **the host's own**, not the PHR's |
| Port | 8001 | the host's |

`app.py` is deliberately thin. Anything of substance belongs in `api.py` or
`bootstrap.py` — otherwise it exists standalone and silently does not exist
when mounted.

## Callback paths this repo owns

| Path | `callback_type` |
|---|---|
| `POST /api/v3/hiu/patient/care-context/on-discover` | `on_discover` |
| `POST /api/v3/hiu/patient/care-context/on-init` | `on_init` |
| `POST /api/v3/hiu/patient/care-context/on-confirm` | `on_confirm` |
| `POST /api/v3/hiu/patient/on-share` | `on_share` |
| `POST /api/v3/hiu/hiecm/subscription-requests/on-init` | `subscription_on_init` |
| `POST /api/v3/hiu/subscription-requests/hiu/notify` | `subscription_notify` |

Plus `GET /phr/health`, which reports `{"status": "healthy", "database": bool}`.

In this chunk these six are **skeletons**: each verifies the inbound ABDM
JWT, archives the payload verbatim to `callback_log`, logs via
`flow_logger`, and returns the standard ack `{"status": "OK"}`. Real
per-callback handling arrives in P3.

## Callback paths this repo deliberately does NOT own

These four are already registered and handled by the existing backend's M3
HIU code (`repo/server/callbacks/router.py`):

```
/api/v3/hiu/consent/request/on-init
/api/v3/hiu/consent/request/notify
/api/v3/hiu/consent/on-fetch
/api/v3/hiu/health-information/on-request
```

**Do not add them here** without an explicit decision about which app owns
the flow. Two routers in one FastAPI app cannot both own a path — whichever
is included first wins, silently, and the other handler simply never runs.
Adding one would work in standalone PHR testing and then quietly break, or
half-work, the moment the two apps are mounted together. If the PHR needs to
participate in those flows, route them in *one* place and fan out.

The list is also kept as data in `aegle_phr/callbacks/router.py`
(`FORBIDDEN_PATHS`) so it can be asserted against.

## Database

Postgres from day one — no `.jsonl` file stores (the existing backend uses
those and it is a known standing caveat).

- SQLAlchemy 2.0 declarative, **sync** engine (psycopg 3, not asyncpg).
- Alembic for schema; `alembic.ini` has no URL in it, `alembic/env.py`
  reads it from settings so no credential is ever committed.
- `bootstrap()` does **not** run migrations. `alembic upgrade head` is an
  explicit step, never something a process does to itself on startup.

Two tables:

- `callback_log` — inbound ABDM callbacks: `id`, `received_at` (timestamptz,
  `now()`), `callback_type`, `request_id`, `correlation_id`, `payload`
  (**JSONB**), `source_ip`; indexed on `received_at` and `request_id`.
- `abdm_call_log` — **outbound** calls to ABDM: `id`, `called_at`, `route`,
  `abdm_url`, `request_body` (JSONB), `response_status`, `response_body`
  (JSONB), `duration_ms`, `error`; indexed on `called_at` and `route`. This
  is how the undocumented response shapes above were recovered. Everything
  written to it passes through `aegle_phr/phr/redaction.py` first.

## Layout

```
aegle_phr/
  settings.py          Settings (pydantic-settings); nothing instantiated at import
  bootstrap.py         the ONLY place with side effects; idempotent
  db.py                sync engine/session; created in bootstrap(), never at import
  models.py            SQLAlchemy 2.0 declarative; CallbackLog, AbdmCallLog
  access.py            X-Aegle-Key gate (app API only, never the callbacks)
  api.py               build_router(settings) -- the mount seam
  app.py               create_app() -- thin standalone wrapper
  __main__.py          python -m aegle_phr, port 8001
  callbacks/
    router.py          the six owned paths + the four forbidden ones
    dispatcher.py      single entry point; NEVER raises
  phr/
    enrollment.py      the five ABDM registration calls; raw bodies returned
    schemas.py         request models only -- no invented response models
    redaction.py       keeps secrets/tokens/PII out of the archive and logs
    call_log.py        writes abdm_call_log; never raises
alembic/               migrations
docker-compose.yml     Postgres 16 on host port 5433
```

## Known gaps

- `abdm_hiu_id` is blank. Whether the PHR registers its own HIU identifier,
  reuses the backend's, or needs none at all is **not confirmed**. Nothing
  in this chunk sends `X-HIU-ID`.
- The six callback paths and their payload shapes come from the task spec,
  **not** from captured live sandbox traffic. This is exactly why the
  payload is stored verbatim as JSONB and nothing beyond `requestId` is
  parsed.
- A request body that is not valid JSON is rejected by FastAPI with a 422
  before it can be archived. Acceptable for a skeleton; revisit in P3 if
  ABDM ever sends one.
- `logs/` and `storage/` contain real bearer tokens and payloads. Both are
  gitignored. Keep it that way.

## Captured ABDM response shapes — mobile registration (P1-A)

**Observed once, on the ABDM sandbox, 2026-08-27. Not specified.** ABDM's
document leaves the "Response Body" section EMPTY for `verify`, `suggestion`
and `enrol`, so everything below is what one real run actually returned —
treat it as evidence, not contract. A second run could differ.

### 1 · `POST /phr/app/enrollment/request/otp` → 200
Matches the documented shape: `{txnId, message}`.

### 2 · `POST /phr/app/enrollment/verify` → 200 — UNDOCUMENTED
```
txnId, message ("OTP Verified Successfully"), authResult ("success"),
users: [ {abhaAddress, fullName, gender, abhaNumber, status, kycStatus, age} ],
tokens: { token, expiresIn: 300, switchProfileEnabled: false }
```
- `users` lists **every** ABHA profile linked to that mobile — including
  profiles belonging to **other people** who share the registered number.
  Ours returned 5 entries, one of them a different individual.
- `tokens.token` is an RS512 JWT, `typ: "Transfer"`, `loginSubject:
  "MOBILE_LOGIN"`, 5-minute life. **Its payload contains the mobile number
  in clear** — see the redaction note below.
- **NOT observed:** what `users` contains when the mobile has no existing
  ABHA address. Presumably `[]`, but that is an inference.

### 3 · `POST /phr/app/enrollment/suggestion` → 200 — UNDOCUMENTED
```
{ txnId, abhaAddressList: [ 10 strings ] }
```
Suggestions come back **without** the `@sbx` suffix (`chordiaaayush1997`),
but `isExists` and `enrol` both expect it suffixed. Append it yourself.

**Not resolved:** whether `email` is required. The spec's parameter table
says required, its own example omits it; we sent one and it was accepted.
The omitted case is still untested on this endpoint.

### 4 · `GET /phr/app/enrollment/isExists` → 200, bare boolean
**`true` = the address is TAKEN. `false` = it is FREE.**

The endpoint name says exactly this, but the spec presents it under an
availability heading and only ever shows the `true` case, which reads as
"yes, available". It is the opposite. Confirmed by calling it twice in one
run: a fresh suggestion returned `false`; an address known to exist (from
`verify`'s own `users` list) returned `true`.

Our route is `/phr/enrollment/address-exists` and returns an explicit
`taken` boolean alongside the raw body so the polarity cannot be misread.

### 5 · `POST /phr/app/enrollment/enrol`

**Failure → 400 with a JSON ARRAY** (not an object) of
`{code, message}`, where `code` is e.g. `"ABDM-9999: "` — trailing
space-colon included.

**Success → 200 — UNDOCUMENTED:**
```
txnId, message ("ABHA Address Created Successfully"),
phrDetails: { firstName, middleName, lastName, fullName, dayOfBirth,
              monthOfBirth, yearOfBirth, dateOfBirth ("20-10-1997"), gender,
              email, mobile, address, stateName, districtName, pinCode,
              stateCode, districtCode, abhaAddress: [ ...ALL addresses... ] },
tokens: { token, expiresIn: 1800,
          refreshToken, refreshExpiresIn: 1296000,
          switchProfileEnabled: true }
```

**`enrol` DOES return session tokens — no separate login step is needed
after registering.** There is no field literally named `X-token`:
- `tokens.token` — RS512 JWT, `typ: "Transaction"`, `system: "ABHA-A"`,
  `requesterId: "PHR-WEB"`, **30 minutes** (`expiresIn: 1800`). Its claims
  embed the full profile, including the mobile in clear.
- `tokens.refreshToken` — RS512 JWT, `typ: "Refresh"`, `system:
  "ABHA-ADDRESS-N"`, **15 days** (`refreshExpiresIn: 1296000`).

`phrDetails.mobile` is returned as **plaintext**, and `phrDetails.abhaAddress`
is the full list of every address on the account, not just the new one.

### Validation behaviour learned the hard way

- **ABDM validates in batches.** The first attempt reported only six address
  errors; email and password were *already* invalid but masked. A shrinking
  error list does not mean the remaining fields are good.
- **Empty strings are rejected** for `address`, `stateName`, `stateCode`,
  `districtName`, `districtCode`, `pinCode` — despite the spec's own example
  showing them as `""`. The spec's recurring example values are accepted:
  `Maharashtra`/`27`, `Nashik`/`123`, `422003`,
  `"Street number 4, Sector 12"`.
- **`email: ""` IS accepted** at enrol. A real gmail address was rejected
  with `ABDM-1006: Invalid Email` — cause unconfirmed, plausibly because it
  is already linked to another ABHA account.
- **Password policy is not in the spec.** A lowercase+digits password was
  rejected with `ABDM-1006: Invalid Password`; one with upper, lower, digit
  and special characters was accepted.

### Redaction consequences

`verify` and `enrol` both return bearer tokens whose base64 payloads contain
the mobile number in clear, so a literal-string scrub cannot catch it.
`aegle_phr/phr/redaction.py` therefore replaces any JWT-shaped value (and
anything under a key containing `token`) with `«redacted-jwt»`, and redacts
`fullName`/`abhaNumber` everywhere — the latter because `users` carries
third-party PII and there is no reliable way to tell at `verify` time which
entry is the person being registered. `abhaAddress` and `txnId` are kept.

## Captured ABDM response shapes — password login (P1-C)

**Observed once, on the ABDM sandbox, 2026-08-28, against `chordiaaayush1997@sbx`
(the address created live in P1-A). Not specified.** Same gap pattern as
P1-A: ABDM's document gives complete request bodies for all three calls but
only documents the two ERROR shapes for `/login/verify`, leaving its
success shape unspecified. Treat everything below as evidence, not
contract — a second run, or a different address, could differ.

### 1 · `POST /phr/app/login/search` → 200

Beyond the six documented fields (`healthIdNumber`, `abhaAddress`,
`authMethods`, `blockedAuthMethods`, `status`, `message`), the real sandbox
response also included **`fullName` and `mobile`, both in plaintext** —
undocumented, and not something the spec's example body even hints at.
`healthIdNumber` came back `null` rather than a string.

**This caused a real redaction gap, found and fixed during this same live
run** (not before it — see "What broke" below).

### 2 · `POST /phr/app/login/verify` → 200 — UNDOCUMENTED, and the real
shape changes the whole flow

```
{ message: "Password verified successfully", authResult: "success",
  users: [ { abhaAddress, fullName, status, kycStatus: "PENDING", age } ],
  tokens: { token, expiresIn: 1800, refreshToken, refreshExpiresIn: 1296000,
            switchProfileEnabled: false } }
```

**There is no top-level `txnId` in this response at all** — not even an
empty string; the field is simply absent. (The `token` JWT's own embedded
claims *do* have a `txnId` key, but its value is `""`.) The spec's step 3
(`/login/verify/user`) needs exactly that field, taken from step 2's
response, to work.

**Decided: step 3 is skipped for password login.** Since `verify`'s own
response already carries a complete `token`/`refreshToken` pair, nothing
was actually missing — password login's `verify` call grants the session
directly, at least on this sandbox as observed. `aegle_phr/phr/login.py`'s
`verify_user()` function and the `POST /phr/login/verify-user` route are
**not removed** over this: ABDM describes that endpoint generically ("verify
the user from the list of ABHA addresses received in the response of verify
OTP/face authentication API"), so an OTP-based login method may still
genuinely need it once built, with a real `txnId` to chain from. It is
simply unused by the password screen, based on what this run actually
showed.

`kycStatus: "PENDING"` here versus `"VERIFIED"` in P1-A's mobile-enrollment
`verify` response for the *same account* is also worth flagging as
unconfirmed-but-real: two different endpoints reporting different KYC
status for one address, on one sandbox, in the same afternoon.

### 3 · `POST /phr/app/login/verify/user` — NOT EXERCISED

Not called in this run, since step 2 already granted a session — see
above. Its documented response shape (`{token, expiresIn, refreshToken,
refreshExpiresIn}`) is unverified against a live call.

### What broke, and what fixed it

`search`'s undocumented `mobile` field is a real phone number, but
`aegle_phr/phr/redaction.py`'s `_CIPHERTEXT_SAFE_PATHS` treats the key name
`mobile` as always holding RSA ciphertext — true for the *enrollment
request* body (P1-A), where a caller always knows the plaintext up front
and passes it as `plaintext_secrets`. It is not true here: this is a
*response*, ABDM chose to echo the number back in clear, and nothing in
`login.py` could have named it in advance. The real mobile number briefly
sat in plaintext in `abdm_call_log` (one row, redacted in place by hand
once found, not deleted). Fixed in `aegle_phr/phr/login.py` only — `_execute()`
gained an `extra_response_secrets` callback that inspects the *parsed*
response body (available only after the call returns) and names additional
plaintext fields to scrub, regardless of any key's ciphertext-safe
exemption. Applied to `search_user()` (confirmed necessary) and defensively
to `verify_password()` (its shape being unknown was the whole reason this
surfaced at all). `redaction.py`'s shared rule was left untouched — it is
still correct for the enrollment flow it was written for.

### Session storage — verified live, not just asserted

`token` confirmed in `sessionStorage` only (absent from `localStorage`);
`refreshToken` confirmed absent from both. The frontend also never
references the string `"refreshToken"` anywhere outside a comment, so the
field is not merely unstored — there is no code path that reads it at all.

## Captured ABDM response shapes — mobile OTP login (P1-D)

**Observed once, on the ABDM sandbox, 2026-08-28, against the same test
mobile number as P1-A/P1-C.** Same gap pattern as every prior chunk: ABDM's
document gives complete request bodies but leaves `/login/verify`'s success
shape unspecified. Treat everything below as evidence, not contract.

### 1 · `POST /phr/app/login/request/otp` → 200
Matches the documented shape exactly: `{txnId, message}`.

### 2 · `POST /phr/app/login/verify` → 200 — UNDOCUMENTED, but answers both
open questions from the task directly

```
{ txnId, message: "OTP verified successfully", authResult: "success",
  users: [ {abhaAddress, fullName, gender, abhaNumber, status, kycStatus, age}, ... ],
  tokens: { token, expiresIn: 300, switchProfileEnabled: false } }
```

**Does `verify`'s success response include a usable `txnId`? Yes —
unlike password login.** The `txnId` in the response body is the *exact
same value* step 1 issued. This is the opposite of P1-C's finding (password
login's `verify` had no top-level `txnId` at all) — the two login methods
genuinely differ here, not just in request shape.

**Does `users[]` match P1-A's enrollment `verify` shape, or differ? It
matches closely — same 6 accounts, same seven fields** (`abhaAddress`,
`fullName`, `gender`, `abhaNumber`, `status`, `kycStatus`, `age`). The same
anomaly recurs: one entry (the KYC-`PENDING` address) is missing
`abhaNumber` entirely, in both P1-A's and this run's `users[]` — consistent
across endpoints, not a one-off glitch. `tokens` here has no `refreshToken`
(P1-A's enrollment `verify` and P1-C's password `verify` both had one;
this one doesn't) — a real, unexplained inconsistency between what look
like the same kind of intermediate token.

### 3 · `POST /phr/app/login/verify/user` — the real finding of this chunk

**First real exercise of this endpoint** (P1-C built it but never called
it — password login's own `verify` granted tokens directly). Calling it
with the documented shape, `{abhaAddress, txnId}`, and the ordinary
gateway-token `Authorization` every other call in this app uses, returned
a **bare 401 with an empty body** — reproduced against two different
linked addresses (one KYC-`PENDING`, one KYC-`VERIFIED`), ruling out the
address as the variable.

A second hypothesis — sending `verify`'s own short-lived (5-minute)
`tokens.token` (`"typ": "Transfer"`) *as* `Authorization` instead of the
gateway token — was also tried and also failed, with a real error body
this time: `{"code": "900901", "message": "Invalid Credentials", ...}`, an
ABDM gateway-level authentication rejection.

**The actual answer, identified by Aayush and confirmed live:** `Authorization`
stays the ordinary gateway token, unchanged — and the transfer token goes
in a **separate header, `T-token`** (value prefixed `"Bearer "`, same as
`Authorization`). With both headers present, the call returns 200 with the
full documented shape: `{token, expiresIn: 1800, refreshToken,
refreshExpiresIn: 1296000, switchProfileEnabled: true}`.

This is a genuinely undocumented API requirement — nothing in the spec
excerpt available for this task names a `T-token` header anywhere.
`login.py`'s `verify_user()` now requires a `t_token` argument (no
default; omitting it is a guaranteed 401, so the signature does not allow
it to be silently forgotten) and sends it exactly this way. The frontend
carries it forward from `verify`'s own response the same way it already
carried `txnId`.

### Cost of finding this

Two OTPs were used in this chunk (the task's usual "request once, verify
once" — an SMS was sent twice specifically because diagnosing the
`verify/user` failure required a second, fresher transfer token after the
first one expired mid-diagnosis; both were explicitly authorized before
being sent). No OTP was wasted on a blind retry — each request-otp call
was a deliberate step in the diagnosis, not a repeat of the same attempt.

## Captured ABDM response shapes — Get All Linked Records

**The spec documents `GET .../hip/v3/link/patient/links` TWICE, with two
contradicting response shapes** — §6.12 ("HIE-CM – Get All Links
Records", Consent Manager section) shows a token/counter-queue record
(`tokenNumber`, `expiresIn`, `counterCode`) that has nothing to do with
"links"; §9.3.5 ("GET All Link records", HIP-Initiated Linking section)
shows a coherent `{"patient": {"id", "links": [...]}}` shape. No saved
Postman example response existed for this call anywhere in Aayush's
workspace before this chunk — this was a genuine first live run, not a
confirmation of an existing capture.

### `POST /phr/links/get-all` (this app's own route; the real ABDM call is `GET .../hip/v3/link/patient/links?limit=-1`) → 200

**§9.3.5's shape is the real one.** Confirmed by Aayush directly ("Im
able to view teh records") — the frontend's parser, which only recognizes
the `patient.links[]` shape, rendered real records rather than falling
back to its "shape didn't match" message. §6.12's token/counter example
was correctly identified as a copy-paste artifact before ever going live
(see `aegle_phr/phr/links.py`'s own module banner for the full reasoning)
and this confirms that judgment call was right.

**Exact field-level values from the live response were not captured into
this file** — the session that ran this test reported the outcome
(records visible, grouped-by-HIP display requested as a follow-up) but
not the raw JSON body itself. If a raw capture is taken later (e.g. via
the Console panel's "Copy" button on this call, with any real patient/HIP
identifiers redacted first), paste it here to complete this section
properly, the same level of detail as every earlier chunk's entry above.

### Frontend: grouped by HIP, not flat

The initial UI rendered one list item per `links[]` entry, which repeats
the same HIP name once per entry when an account has several linked
records under one HIP. Changed (Aayush's explicit request, after seeing
the flat version live) to one collapsible section per HIP
(`testui/src/routes/HomeScreen.tsx`'s `groupByHip()`), collapsed by
default, matching `ConsolePanel.tsx`'s own "▸ closed / ▾ open" convention.
