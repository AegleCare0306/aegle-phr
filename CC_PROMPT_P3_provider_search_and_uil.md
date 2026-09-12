# P3 — Provider Search + User-Initiated Linking (spec §10)

**Model recommendation: Sonnet, extended thinking ON.** This is a bigger architectural step than
anything since P0 — new callback infrastructure, a new cross-process correlation store, and (per the
roadmap's own framing) **the first full live round trip between your two repos** — your PHR raises a
real discovery against your own HIP and your own HIP answers it. Give this one real thinking budget,
not just wiring.

## Standing requirements, both still in force

**Real-app navigation** (Aayush, 2026-08-31): this is not optional per-chunk — every screen this
chunk adds must fit into the app the way a shipped app would. Concretely here: "Find my records"
(the whole discover→link flow) should be reachable from the logged-in home/profile screen, not a
disconnected route the user has to already know exists; a successful link should show up somewhere
real (a "linked records" list), not just a toast; the flow should read as one continuous journey —
search a provider → discover → review found care contexts → enter the OTP → see confirmation — not
four separate unconnected screens.

**Verify-before-trusting-status**: this file's own research below was built by reading the actual
running code (`repo/server/config.py`, `repo/server/linking.py`, `repo/server/callbacks/router.py`,
`repo/server/callbacks/repository/care_context_notify_repository.py`) directly, not from memory or
assumption — re-confirm anything below still holds before building, the same way every prior chunk in
this project has had to.

## What this phase is, and why it's different from everything built so far

Spec §10, roadmap Block B ("Provider discovery + User-Initiated Linking · 15 endpoints · new (patient
side)"). Everything built in P1 was **synchronous**: call ABDM, get a real answer back in the same
response. This phase is **asynchronous**: the three core UIL calls (discover, link-init, link-confirm)
all return a bare `202 Accepted` with no useful body — the real answer arrives LATER, as an inbound
callback ABDM's gateway sends to a URL your own backend must expose. Nothing built so far in
`aegle-phr` receives an inbound callback; `repo/`'s existing HIP-side code does, and its pattern
(`server/callbacks/utils/json_file_store.py`, `server/callbacks/repository/
care_context_notify_repository.py`) is the direct model to mirror.

**Confirmed live-code fact, not a guess**: your own HIP (`repo/`) already implements the OTHER side
of this exact exchange — `discover_service.py`, `link_init_service.py`, `link_confirm_service.py`
receive the HIP-facing callbacks and answer with `send_on_discover()` (in `server/linking.py`). This
phase is what the roadmap calls "the loop-closing block": your PHR (acting as HIU) can discover
against your OWN HIP (`IN3310002215`, "Aayush Health Care", per `repo/server/config.py`'s `HIPS`
list) and get a real, non-mocked answer — no dependency on ABDM's own reference apps for testing.

## An open question that MUST be resolved before any live UIL call — flagged, not guessed

Every one of the three outbound calls (discover, link-init, link-confirm) requires an `X-HIU-ID`
header — the identifier of YOUR app acting as the Health Information User. **What that value actually
is has not been confirmed anywhere in this project.** `repo/server/config.py` has a `HIPS` list (4
registered HIP-role facility IDs) but no equivalent `HIU_ID` constant — every existing use of
`hiu_id` in the repo is a variable threaded through from elsewhere (an inbound consent's own `hiu.id`
field), never a fixed value for "us." The roadmap's own text says "your PHR raises a discover against
your own HIP (`IN3310002215` / `IN2410002590`)" — naming two HIP IDs, not resolving which one, and
not naming an HIU ID at all.

**Do not guess this.** Sending the wrong `X-HIU-ID` could silently misroute every call in this chunk
or waste a real OTP (link-confirm consumes one, sent to the patient's real mobile via the HIP). Before
building the live-call path: check whether `SBXID_046112`'s ABDM sandbox bridge registration includes
an HIU-role facility ID (Aayush may need to check the ABDM sandbox portal directly, or this may
already be one of the two HIP IDs playing double duty — HIP and HIU roles CAN share one facility ID
in ABDM's model). Build everything else first (the calls, the callback receivers, the correlation
store, provider search) with this as a clearly-labeled placeholder/config value, and confirm it before
the first live `discover()` call.

## Provider Search (§10.3.13–§10.3.15) — build this part first, no open questions, no auth complexity

Three simple GETs against `GATEWAY_BASE_URL = "https://dev.abdm.gov.in/api/hiecm/gateway/v3"`
(confirmed directly from `repo/server/config.py` — this is a THIRD host, distinct from both
`abhasbx.abdm.gov.in` (PHR/enrollment/login/profile) and `healthidsbx.abdm.gov.in` if that's used
elsewhere — don't default to either of those for this family).

- **All Providers** (§10.3.13): `GET {gateway}/providers?stateCode=-1&districtCode=-1&name=<query>`
  — search by state/district/name (`-1` means "any"). Response: an array of facility objects
  (`identifier.name`, `identifier.id`, `facilityType[]`, `isHIP`, `isGovtEntity`, `endpoints`).
- **Provider by ID** (§10.3.14): `GET {gateway}/providers/{hipId}` — single facility object.
- **Govt Programs** (§10.3.15): `GET {gateway}/govt-programs` — array of `{identifier:{name,id},
  facilityType[], isHIP}`.

**Headers — spec vs. Postman disagree, send the superset (same pattern as every prior chunk)**: the
spec's own header table for all three lists ONLY `REQUEST-ID`/`TIMESTAMP`/`X-CM-ID` — no
`Authorization` row at all. But Aayush's Postman collection's saved requests for all three DO use a
bearer-auth block. Send `Authorization: Bearer <gateway token>` (cheap, safe, matches the pattern
already established for other endpoint families in this project) alongside `REQUEST-ID`/`TIMESTAMP`/
`X-CM-ID: sbx`. No `X-AUTH-TOKEN`, no `X-HIU-ID` needed for these three specifically — neither the
spec nor Postman shows them here, and these calls aren't patient-scoped (they're general directory
lookups). No encryption anywhere in this family — nothing here is a secret value.

Build a simple search screen: state/district/name filters (or free-text against `name`, your call —
`stateCode`/`districtCode` need real ABDM code values which aren't confirmed anywhere in this
project yet, so a name-only search is the safer default unless you find where those codes are
documented), a results list, and a detail view via provider-by-id. This becomes the entry point for
the UIL flow below — the user picks a provider from this search before starting a discovery.

## User-Initiated Linking (§10.3.1–§10.3.12) — the real work of this phase

Base URL: `HIECM_BASE_URL = "https://dev.abdm.gov.in/api/hiecm"` (confirmed from
`repo/server/config.py` — same host as provider search, different path family:
`/user-initiated-linking/v3/...`).

**Headers for the three OUTBOUND calls (discover, link-init, link-confirm) — a genuinely different
header family from everything built in P1**: per the spec's own header tables AND
`repo/server/linking.py`'s own commented-out (but structurally complete and clearly-reasoned)
reference implementation of this exact call shape: `Authorization: Bearer <gateway token>` (as
always) PLUS **`X-AUTH-TOKEN: Bearer <the patient's own PHR session token>`** — note this is the
literal header name `X-AUTH-TOKEN`, NOT `X-token` like every Profile-family call in P1-M/P1-N. Don't
default to `X-token` out of habit. Also `X-CM-ID: sbx`, `X-HIU-ID: <see open question above>`,
`REQUEST-ID`, `TIMESTAMP`. These three calls require the user to be logged in — pull the session
token the same way `profile.py`/`profile_link.py` already do (`getSessionToken()` on the frontend).

**No encryption anywhere in this family — a real, confirmed difference from every other flow built
so far**: every spec example shows `unverifiedIdentifiers[].value`, `transactionId`, `linkRefNumber`,
and even the confirm step's `token` (the OTP itself!) as PLAIN values — never a `"{{encrypted ...}}"`
placeholder the way every other OTP flow in this project has been. This is worth double-checking on
the first live call (the same way this project has been bitten before by wrong certificate
assumptions), but don't build encryption into this module preemptively — the spec's own examples are
consistent and unambiguous on this point across all three calls.

### §10.3.1 Discover (`POST /user-initiated-linking/v3/patient/care-context/discover`)
Body: `{"hipId": "<chosen provider's id>", "unverifiedIdentifiers": [{"type": "ABHA_ADDRESS", "value":
"<the user's own ABHA address, plaintext>"}]}`. Response: bare `202 Accepted`, nothing useful in the
body. **The `REQUEST-ID` header value YOU send is the correlation key** — the async answer (below)
comes back carrying `response.requestId` equal to that same value.

### §10.3.4 on-discover callback (`POST /api/v3/hiu/patient/care-context/on-discover`, inbound)
This is what your backend must EXPOSE and receive — ABDM's gateway calls YOU. Body carries
`transactionId`, either a `patient[]` array (each with `referenceNumber`, `careContexts[]`, `hiType`,
`count` — the actual matched records) or an `error` (e.g. `{"code":"ABDM-1010","message":"Patient not
found"}`), and `response.requestId` (matches your original discover call's `REQUEST-ID`). Respond
`200 OK` with an empty/ack body — no processing needed in the response itself.

**Storage**: stash this callback's full body, keyed by `response.requestId`, in a new file-backed
store mirroring `repo/server/callbacks/utils/json_file_store.py`'s pattern (`set_key`/`get_key`,
JSON-lines file under a `storage/` directory) — build an equivalent small module in `aegle_phr/`
rather than importing `repo/`'s (read-only reference; this project's standing rule). The frontend
polls a new `/phr/uil/discover/result?requestId=...` route (or similar) that reads this store — since
there's no websocket/push to the browser, polling every 2-3s for a short window (say 30s, matching
how long ABDM's own callback is expected to take) is the reasonable default; if nothing arrives, show
a timeout state, not an infinite spinner.

### §10.3.5 Link init (`POST /user-initiated-linking/v3/link/care-context/init`)
Called once discover has returned real matches the user wants to link. Body: `transactionId` (from
discover), `abhaAddress`, and the SAME `patient[]`/`careContexts[]` shape discover's callback returned
(echoed back — the user is confirming which of the discovered records to link, not supplying new
data). Response: bare `202 Accepted`. **This is the step that makes the HIP send a real OTP to the
patient's real registered mobile** — treat it with the same live-testing care as every other
OTP-sending call in this project (explicit permission before triggering it).

### §10.3.8 on-init callback (`POST /api/v3/hiu/patient/care-context/on-init`, inbound)
Carries `transactionId`, a `link` object (`referenceNumber` — this is `linkRefNumber`, needed for the
confirm step below — plus `authenticationType`, `meta.communicationMedium`/`communicationHint`/
`communicationExpiry`), or an `error`, and `response.requestId`. Same storage/polling pattern as
on-discover.

### §10.3.9 Link confirm (`POST /user-initiated-linking/v3/link/care-context/confirm`)
Body: `{"token": <the OTP the user just typed, as a NUMBER per the spec's own example — not a
string>, "linkRefNumber": "<from on-init's link.referenceNumber>"}`. Response: bare `202 Accepted`.

### §10.3.12 on-confirm callback (`POST /api/v3/hiu/patient/care-context/on-confirm`, inbound)
Carries the final `patient[]` (now confirmed-linked care contexts) or an `error`, and
`response.requestId`. Same storage/polling pattern. **This is the actual "you now have linked
records" moment** — per the real-app-navigation requirement above, a successful on-confirm should
land the user on a real "linked records" view, not just a success message.

## Router wiring — confirmed, no repo/ changes needed

`aegle_phr.api.build_router()` returns a plain `APIRouter()` mounted via
`app.include_router(phr_build_router(settings))` in `repo/server/main.py` with NO prefix — confirmed
directly from that file. That means the three new inbound callback routes
(`/api/v3/hiu/patient/care-context/on-discover`, `on-init`, `on-confirm`) can be added as
NON-`/phr`-prefixed absolute routes inside the SAME `build_router()` function, and they'll mount
correctly without touching `repo/` again. Confirmed no collision: `repo/server/callbacks/router.py`
already claims the HIP-facing side of this exchange (`/api/v3/hip/patient/care-context/discover`,
`/api/v3/hip/link/care-context/init`, `/api/v3/hip/link/care-context/confirm` — different paths,
different direction, already built, don't touch), and the roadmap's own callback-collision analysis
confirms these three HIU-facing paths are free through P4.

## What to build

1. Provider search (all-providers, provider-by-id, govt-programs) — simple, do this part first.
2. `aegle_phr/phr/uil.py` (or similar new module, your naming call) — `discover()`, `link_init()`,
   `link_confirm()`, matching this project's existing per-module `_headers()`/`_execute()` shape
   (duplicate the small helpers, don't import across modules — established convention).
3. A small correlation store (new module, mirrors `json_file_store.py`'s pattern) + the three inbound
   callback route handlers in `build_router()`, storing each callback's body keyed by
   `response.requestId`.
4. A polling result route the frontend can call to check whether a callback has arrived yet.
5. Frontend: provider search screen → discover (with a real-app-appropriate loading/waiting state
   while polling) → review matched care contexts → link-init → OTP entry → link-confirm → a real
   "linked records" view showing what's now linked. One continuous flow, per the standing navigation
   requirement.

## Explicitly NOT in scope for this chunk

Anything about consent (grant/deny/revoke) — that's P4, a different spec block (§6), and UIL's own
job stops at LINKING care contexts, not requesting access to the data inside them. Actually reading/
displaying the linked health records — that's P5 (FHIR reader, doesn't exist yet). HIP-side changes
of any kind — `repo/` stays read-only reference; if `discover_service.py`/`link_init_service.py`/
`link_confirm_service.py` don't work as expected during live testing, report exactly what happened,
don't patch `repo/` to make it pass.

## Verification

Offline: read every new file back, confirm the host/path/header choices above, confirm the new
callback routes don't collide with `repo/server/callbacks/router.py`'s existing list, confirm the
correlation store's key (`response.requestId`) actually matches what you send as `REQUEST-ID` on each
outbound call.

Live (ask permission before each step — this consumes a real OTP partway through, and is the first
chunk in this project to depend on a second local server (`repo/`'s own HIP callback handling) also
being up and reachable via the same ngrok tunnel):
1. Provider search first — no side effects, free to retry, resolves whether the header/host choices
   above actually work.
2. Confirm the `X-HIU-ID` question above is resolved BEFORE step 3.
3. Discover against your own HIP (`IN3310002215`) using a real ABHA address that has actual linked
   records at that HIP (if none exists, say so rather than fabricating a positive result) — confirm
   the on-discover callback actually arrives and correlates correctly.
4. Link-init only with explicit go-ahead (real OTP to a real phone) — confirm on-init arrives with a
   usable `linkRefNumber`.
5. Link-confirm with the real OTP — confirm on-confirm arrives and the records show up in the new
   "linked records" view.

## Ground rules (standard, repeated)

No throwaway scripts left behind. Detailed per-file change report plus a short Cowork-pasteable
summary. Strict scope discipline — flag anything else you spot, don't fix it, only fix bugs you
introduce this chunk. No git commit/push/init. Never delete/truncate existing `logs/`/`storage/`
content. Don't claim something works without running it. Flag uncertainty visibly — especially the
X-HIU-ID question, and whether the "no encryption in this family" reading holds up live. Never print
the access key, client secret, plaintext OTP, mobile number, email address, password, or any live
token into any report. Do not modify `repo\` (read-only reference) — if something there needs a fix
to make this chunk work, report it, don't patch it. Headers: `Authorization` (gateway) always; add
`X-AUTH-TOKEN` (not `X-token`) + `X-HIU-ID` for the three UIL outbound calls specifically; provider
search needs only `Authorization` + `X-CM-ID`; the three inbound callbacks need no outbound headers
at all (you're receiving, not authenticating an outbound call).
