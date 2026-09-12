# Chunk: View All Linked Records ("Get All Link Records")

**Recommended model/effort: Sonnet, extended thinking ON.** Not because this endpoint is
complicated — it's a single unauthenticated-body GET, no OTP, no encryption — but because the
spec documents it twice with two disagreeing response shapes and you need to read both, form a
judgment about which to trust, and say so in the code, the same way every other spec/Postman
disagreement in this project has been surfaced rather than silently resolved. Rushing this one
risks modeling the wrong response shape from the start.

## Why this chunk, and why now

Aayush's own words, directly: *"UIL will be my last step. The first thing I want to implement is
being able to see all the linked data to my account."* That reorders the roadmap: User-Initiated
Linking (discovering and linking NEW records — spec section 10, the CC_PROMPT_P3 prompt you may
already have) is now explicitly LAST. This chunk — showing records ALREADY linked to the logged-in
user's account — goes first, and is unrelated to P3's async discover/init/confirm machinery. It is
a plain synchronous GET call. Do not build any part of P3's UIL flow as part of this chunk.

"Already linked" here mostly means care contexts a HIP linked to this ABHA address through
HIP-Initiated Linking (spec section 9) — a flow this project's `repo/` backend already implements
server-side (nothing new needed on that side). This chunk is purely about *displaying* what's
already there, from the PHR app's own side.

## Standing requirements (apply to this chunk like every other)

- **Real-app navigation, not a bolt-on test screen.** Aayush's own words, said once and now
  standing for every chunk: *"We are building an app, it might be for testing but the design has
  to be like an app, I don't want to keep telling things like after login I go should go to a
  different page which has my details extra — that is a design which should be inherent in all
  steps."* Concretely for this chunk: a logged-in user should be able to reach their linked
  records from where they already are — `testui/src/routes/HomeScreen.tsx` (the post-login landing
  page) or `ProfileScreen.tsx` (the full profile view) — not a route nobody ever navigates to
  without being told the URL. See "Frontend" below for the concrete suggestion.
- **Verify, don't assume.** This call has never been made against the sandbox — the response
  shape below is the best-supported reading of the spec, not a captured example. Say clearly what
  is confirmed vs. hypothesized, the same as every other module banner in this repo.
- Every other standing ground rule from prior chunks applies unchanged (see bottom of this file).

## The spec documents this endpoint TWICE — read both, here's why one wins

The exact same URL is documented in two different sections of `ABHA_PHR_V3_Documents` v1.1, with
genuinely different header requirements and response examples. Both are quoted below in full —
don't take my summary's word for it, read them yourself in the spec if you have it, because the
judgment call below matters for what you build.

**Section 6.12 — "HIE-CM – Get All Links Records"** (Consent Manager section):

> This API will be invoked by HIU to get the All links.
> URL: `api/hiecm/hip/v3/link/patient/links?limit=-1`
> Request: GET
>
> Header Parameters:
> - REQUEST-ID — Yes — Unique UUID for track the end to end request transaction
> - TIMESTAMP — Yes — ISO date-time
> - X-CM-ID — Yes — `sbx`
> - X-AUTH-TOKEN — Yes — "JWT Access token which was issued by PHR service after successfully
>   user authentication. If HIP does not have any role, then it is mandatory"
>
> Response:
> ```json
> [
>   {
>     "id": 20744,
>     "patientId": "hitit@sbx",
>     "tokenNumber": "19",
>     "hipId": "MAYUR_HIP",
>     "hipName": "MAYURHIP",
>     "hipAddress": "DEFAULT",
>     "expiresIn": "180",
>     "clientId": "MAYUR_HIU",
>     "dateCreated": "2024-12-23T10:15:39.581Z",
>     "counterCode": "123456"
>   }
> ]
> ```

**Section 9.3.5 — "GET All Link records"** (HIP-Initiated Linking section):

> This API provide all the linked care contexts for ABHA Address.
> URL: `/api/hiecm/hip/v3/link/patient/links`
> Request: GET
>
> Header Parameters:
> - Authorization — Yes — "JWT Access token which was issued by ABDM session API after
>   successful validation of client id and secret"
> - REQUEST-ID — Yes — UUID
> - TIMESTAMP — Yes — ISO date-time
> - X-AUTH-TOKEN — "JWT Authentication token which was issued by ABDM after successful
>   validation of username and password"
> - X-CM-ID — Yes — `sbx`
>
> Request Params: `limit` — example value `100` — "Number of records to be fetched from the
> database."
>
> Response:
> ```json
> {
>   "patient": {
>     "id": "user_1992@sbx",
>     "links": [
>       {
>         "hip": { "id": "TestClinicHIP", "name": "TestClinicHIP", "type": "HIP" },
>         "referenceNumber": "user_1992@sbx",
>         "display": "User Record",
>         "hiType": "HealthDocumentRecord",
>         "careContexts": [
>           {
>             "referenceNumber": "e707c945-3672-4b85-8525-4c7e620ef301",
>             "display": "Visited on 08-Feb-2024 09:00:00 Visit Type as Out Patient"
>           }
>         ],
>         "dateCreated": "2024-07-18T11:49:15.736Z"
>       }
>     ]
>   }
> }
> ```

**These disagree on both headers and response shape for the identical URL.** §6.12's example is
almost certainly a copy-paste error from an unrelated part of the spec: it's shaped like a
token-queue/counter record (`tokenNumber`, `expiresIn`, `counterCode`) — nothing about "links" —
and it's the only one of the two that omits `Authorization` from its own header table, which would
be an odd omission given every other GET in this app sends it.

**Trust §9.3.5's response shape.** It's internally coherent (a patient object containing an array
of HIP links, each with its own care contexts — exactly the shape "records linked to my account"
should have) and matches this project's standing rule: when a spec disagrees with itself, prefer
the coherent/complete source over the one that looks like a copy-paste artifact. Model the
response type on §9.3.5's example. Still archive the RAW response verbatim regardless of which
shape actually comes back — same `_passthrough()` convention every other route in this app already
uses — so if the real answer turns out to look like §6.12 instead, nothing is lost or misparsed
into an exception.

**On headers: send the superset.** Same call this project has made every time the spec disagrees
with itself on headers (see `aegle_phr/phr/profile.py`'s own `_headers()` sending both
`Authorization` and `X-Token` when the spec's own tables disagreed) — send **all** of:
`Authorization` (gateway bearer token), `X-AUTH-TOKEN` (the patient's session token), `X-CM-ID`,
`REQUEST-ID`, `TIMESTAMP`. Costs nothing extra, and §9.3.5's table (the one to trust) already lists
all five as required/expected.

**One naming trap:** the session-token header here is the literal string `X-AUTH-TOKEN` — NOT
`X-Token` like `profile.py`/`profile_link.py` use elsewhere in this app. Don't copy those modules'
header dict verbatim; the header *name* is different even though the *value* (the same session
token from `session.ts`) is the same.

## Postman evidence

Searched all five collections in Aayush's "Aegle Care's Workspace". Exactly one saved copy exists:
collection **"PHR"** → folder **"Consent Manager"** → subfolder **"HIU & HIP"** → request
**"links"**.

- `GET {{base-url}}/api/hiecm/hip/v3/link/patient/links?limit=-1` — confirms §6.12's `limit=-1`
  URL-embedded style is the one actually used in practice, not §9.3.5's separate `limit=100`
  query-param example. Default to `limit=-1` (all records); make it an optional parameter if you
  want a caller to be able to request fewer.
- Auth: a Postman `bearer` auth block (`{{BEARER_AUTH}}`) **plus** literal header rows for
  REQUEST-ID, TIMESTAMP, `X-AUTH-TOKEN` (`{{auth-token}}`), and `X-CM-ID` (`{{cm-id}}`) — three
  simultaneous auth/identity mechanisms, consistent with "send the superset" above.
- **No saved example response exists for this request anywhere in the workspace.** The response
  shape is genuinely unconfirmed until you run it live — treat §9.3.5's example as the best-
  supported hypothesis, not a certainty.

## Host, and why no new settings field is needed

This is a HIE-CM (Health Information Exchange – Consent Manager) endpoint, not an ABHA-identity
endpoint — it lives under `hiecm`, not `abha`. Confirmed directly from `repo/server/config.py`
during P3's research: `HIECM_BASE_URL = "https://dev.abdm.gov.in/api/hiecm"`. `aegle_phr/settings.py`
already has this exact field — `abdm_hiecm_base_url` — sitting unused so far (P3 will be the other
consumer of it, once you get to it). Use it here:

```
url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/hip/v3/link/patient/links"
```

`settings.abdm_x_cm_id` (already `"sbx"`) is the `X-CM-ID` header value — also already sitting
unused, also already exactly right for this.

## No encryption — this is a plain GET, no body

Nothing here is RSA-encrypted. There's no request body at all (GET with query params only), so
none of `CERTIFICATES.md`'s rules apply to this chunk — don't call `get_public_certificate()` or
`encrypt_value()` anywhere in this module.

## The concrete pattern to mirror

`aegle_phr/phr/profile.py`'s `get_profile()` is the closest existing analog — a GET, no body, one
session-token header, archived via the same `_passthrough()`/`archive()` convention. Read that
function and its neighboring `_headers()`/`_execute()` helpers directly before writing this
module; mirror the *shape* of that pattern (a private `_headers()` builder, a private `_execute()`
wrapper around `call_with_retry()` that archives every call via `aegle_phr/phr/call_log.py`'s
`archive()`), but do NOT reuse `profile.py`'s own `_headers()` — build a new one, since the header
set and the base URL are both different here (X-AUTH-TOKEN + X-CM-ID + Authorization, hitting
`abdm_hiecm_base_url`, not X-Token alone hitting `abdm_abha_base_url`).

Suggested new module: `aegle_phr/phr/links.py`. Something like:

```python
def get_all_linked_records(settings: Settings, x_auth_token: str, limit: int = -1) -> AbdmResult:
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/hip/v3/link/patient/links"
    ...
```

Wire it into `aegle_phr/api.py`'s `build_app_api_router()` the same way every other route is wired
— a new `@router.get(...)` (or POST if you'd rather keep the same POST-with-body convention this
app uses everywhere else for consistency with its own test-UI access-key gating; either is fine,
just be consistent with how `xToken`-style routes already take a small Pydantic body in this app
rather than a bare query string, since that's the existing convention in `schemas.py`).

## Frontend — where this needs to live

Per the standing real-app-navigation requirement: this is exactly the kind of thing a real PHR app
shows on (or one tap from) its home screen, not a page nobody finds. Two reasonable places, your
call which fits better once you're looking at the actual screens:

1. **A new section on `HomeScreen.tsx`** (the post-login landing page), alongside the existing
   ABHA Number/Address display — e.g. a "Linked Records" card that fetches and lists them, or a
   button that reveals the list inline.
2. **A new section on `ProfileScreen.tsx`**, following the exact same expand/collapse panel
   pattern already used there for Link ABHA Number, Switch Profile, etc. (see that file — every
   feature is a `<button>` that reveals a sub-panel).

Either way: reachable from a page the user is already on after logging in, not a new top-level
route that only exists if someone knows to type `/links` in the address bar. If you do add a
dedicated route (e.g. `/profile/links`) for a cleaner sub-view, make sure a button on `Home` or
`Profile` actually navigates there — don't leave it orphaned in `App.tsx`'s route table only.

## What to build

1. `aegle_phr/phr/links.py` — the ABDM call itself (`get_all_linked_records()`), following the
   pattern above. Module banner should document the §6.12-vs-§9.3.5 contradiction in your own
   words (don't just copy this prompt), which shape you're trusting and why, and that the response
   is unconfirmed against a live capture.
2. A new route in `aegle_phr/api.py`'s `build_app_api_router()`, plus whatever new Pydantic body/
   response types `schemas.py` needs (following the existing naming conventions there).
3. A new `api/endpoints.ts` function + types in `testui/src/api/`, following the same pattern as
   `getProfile()`.
4. The frontend surface described above (Home or Profile section, your call).
5. Update `README.md`'s captured-shapes section with whatever ABDM actually returns once you test
   this live — flagged as a gap in this project already (nothing's been recorded there past an
   earlier chunk), and this is a good chunk to start closing it on, since this response shape is
   currently pure hypothesis.

## Explicitly NOT in scope for this chunk

- User-Initiated Linking (spec section 10) — discovering and linking NEW records. Aayush's own
  words: that's last. Don't start on `CC_PROMPT_P3_provider_search_and_uil.md` as part of this
  chunk.
- Consent request/approval flows (spec section 6, beyond this one GET) — a later phase.
- Reading actual FHIR health records/documents — a later phase (this chunk shows *that* a care
  context is linked, not its clinical content).
- Any change inside `repo/` — read-only reference, as always.

## Verification

This is the lowest-risk live call in this project so far: a side-effect-free GET, no OTP consumed,
no state changed on ABDM's side by calling it. You do NOT need Aayush's explicit go-ahead before
testing this live the way P1/P3's OTP-consuming steps do — a repeated GET costs nothing. Still:

1. **Offline first**: confirm the route wires up, the request builds with the right host/headers/
   query string, and a mocked/stubbed response round-trips into the frontend correctly.
2. **Live, as soon as offline checks pass**: call it against the real sandbox with a real logged-in
   session token. Report exactly what comes back — which of the two documented shapes (or a third,
   different one) ABDM actually returns — and update this module's banner and `README.md`
   accordingly. This is the single most useful piece of new information this chunk can produce for
   the rest of the project, since nothing here was previously confirmed against a live capture.
3. Confirm the frontend surface is actually reachable by clicking through the app as a user would,
   not just by hitting the route directly — per the standing real-app-nav requirement.

## Ground rules (standard, unchanged from every prior chunk)

- No throwaway scripts left behind in the repo.
- Deliver a detailed per-file change report, plus a short Cowork-pasteable summary at the end.
- Strict scope discipline: if you spot something else worth fixing, flag it, don't fix it — only
  fix bugs you introduce in this chunk.
- No git commit, push, or init.
- Never delete or truncate existing `logs/` or `storage/` content.
- Don't claim something works without actually running it.
- Flag any uncertainty visibly rather than silently picking an answer.
- Do not modify anything under `repo/` — read-only reference only.
- Never print the access key, client secret, plaintext OTP, mobile number, email address,
  password, or a live token into any report.
- Use `Authorization: Bearer <gateway token>` (never `apikey`) for the gateway credential, exactly
  as every prior chunk has, alongside `X-AUTH-TOKEN` for the session token this chunk specifically
  needs.
