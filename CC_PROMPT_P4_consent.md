# Chunk: Consent Manager — all 11 patient-facing flows (spec §6 + Postman's approve endpoint)

**Recommended model/effort: Sonnet, extended thinking ON.** This is the biggest single chunk since
P1-E/P1-F: 11 endpoints, several genuinely interdependent (approve's body is built FROM
request-details' own response, not independently), and — flagged prominently below — every one of
them has ZERO saved example responses anywhere in Postman. That combination (real interdependency +
no ground truth on responses) means real design judgment is needed, not just wiring up 11 passthrough
calls. Treat it with the same seriousness as P1-E/F, not as eleven small chunks glued together.

## Where this fits

Spec §3 (enrollment/login/profile) and "View All Linked Records" (spec §6.12/§9.3.5 — you can SEE
what's linked to your account) are both built and working. This chunk is Consent: the mechanism that
lets a patient actually control who gets to READ the data behind those linked records. It does not
itself fetch any health-record content — that's spec §7 "Data Flow", a separate, later phase (not
part of this chunk, don't build it here). This chunk is entirely about the request/approve/deny/
revoke lifecycle.

**Aayush's own priority, direct**: he asked for the flows list first, then said to build a prompt for
all of them — no sub-ordering given beyond that, so this prompt follows Postman's own numbering
(01-11) as the build order, since it reads as a sensible one (view before you can act, act before you
can revoke). Flag it if any part of that order turns out to be wrong once you're actually building.

## Standing requirements (apply here like every other chunk)

- **Real-app navigation.** Aayush's own words, standing for every chunk: a logged-in user should
  reach this from where they already are, not a route nobody navigates to. See "Frontend" below for
  the concrete suggestion — this is a big enough feature to deserve its own screen, unlike "View
  Linked Records," which was small enough to live inline on Home.
- **Cross-reference Postman before calling anything spec-undocumented.** This is the standing lesson
  from THIS chunk's own research: the spec PDF has no "approve" endpoint at all, but a complete one
  exists in Postman. Every endpoint below has been checked against both sources already — but if you
  hit something during implementation that looks off, check Postman again before assuming the spec is
  complete.
- **Verify, don't assume.** None of these 11 calls have ever been run against the sandbox. Every
  response shape below is either the spec's own example or inferred from the request body alone — say
  clearly, in each function's own docstring, which is which, the same way `links.py` documents its
  own SS9.3.5-vs-SS6.12 judgment call.
- Every other standing ground rule applies unchanged (see bottom of this file).

## Host, headers, encryption — all already established, nothing new to figure out

Every one of these 11 calls uses the exact same convention `aegle_phr/phr/links.py` already uses and
has already confirmed live (that chunk's own first real run matched this shape) — **read `links.py`
directly before writing anything here; it is the template to mirror, more so than `profile.py`, since
it's the same host and header family, not just a similar pattern**:

- **Host**: `settings.abdm_hiecm_base_url` (`https://dev.abdm.gov.in/api/hiecm`), NOT
  `abdm_abha_base_url`. Already in `settings.py`, already used by `links.py`.
- **Headers**: `Authorization` (gateway bearer token, via `get_gateway_token()`) + `X-AUTH-TOKEN`
  (the patient's session token — literal header name, NOT `X-Token` like `profile.py`/
  `profile_link.py`) + `X-CM-ID` (`settings.abdm_x_cm_id`, already `"sbx"`) + `REQUEST-ID` +
  `TIMESTAMP`. Same superset-sending convention as `links.py`'s own `_headers()` — mirror that
  function almost verbatim, just parameterized per call the way `links.py` already is.
- **No encryption anywhere in this chunk.** Every one of these 11 requests is a plain JSON body or a
  plain GET — none of `CERTIFICATES.md`'s rules apply. Don't call `get_public_certificate()`/
  `encrypt_value()` anywhere in this module.
- **Response parsing**: same discipline as `links.py` — return ABDM's raw body untouched from every
  function (never gate on a Pydantic model), and document your best-guess response shape as a
  separate `BaseModel` "contract" purely for the frontend's benefit, exactly like
  `GetAllLinkedRecordsResponse` does. Since NOTHING here has a saved live example, this matters more
  in this chunk than it did even for `links.py`.

## The 11 endpoints, in the order to build them

All 11 live under `/api/hiecm/consent/v3/...` on the HIE-CM host. Confirmed via both the spec
(`ABHA_PHR_V3_Documents` §6.13-6.22) and Postman's "PHR" collection → "Consent Manager" →
"FETCH & MANAGE CONSENT REQUESTS" folder (numbered 01-11 there, matching this order) — Postman is the
source of truth for anything spec-silent, per the standing lesson above.

**1. Auto-approve** — `POST /api/hiecm/consent/v3/auto/approve` (spec §6.13). Body:
```json
{
  "isApplicableForAllHIPs": true,
  "hiu": { "id": "{{hiu-id}}" },
  "includedSources": [{
    "hiTypes": ["Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
                "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice"],
    "purpose": { "text": "Care Management", "code": "CAREMGT", "refUri": "www.abdm.gov.in" },
    "period": { "from": "...", "to": "..." }
  }],
  "excludedSources": []
}
```
Sets a standing policy: future consent requests from this HIU (or all HIPs, per the flag) matching
these hiTypes/purpose/date-range auto-grant without the patient reviewing each one. `202 Accepted`
expected, no documented response body either place.

**2. Disable auto-approve** — `POST /api/hiecm/consent/v3/auto/approve/{consentId}/disable` (spec
§6.14). No body. **3. Enable auto-approve** — same URL with `/enable` (spec §6.15). No body. Both
`202 Accepted`.

**4. All consent requests** — `GET /api/hiecm/consent/v3/request?limit=10&offset=0&status=ALL` (spec
§6.16). The inbox. Spec's own example response:
```json
{
  "size": 10, "limit": 10, "offset": 0,
  "requests": [{
    "requestId": "...", "purpose": {"text","code","refUri"}, "patient": {"id"},
    "hip": {"id","name","type"}, "hiu": {"id","name","type"},
    "careContexts": [{"patientReference","careContextReference"}],
    "requester": {"name","identifier": {"value","type","system"}},
    "status": "GRANTED", "createdAt": "...", "lastUpdated": "...",
    "hiType": [...], "permission": {"accessMode","dateRange","dataEraseAt","frequency"}
  }]
}
```
`limit`/`offset`/`status` should all be caller-overridable params, defaulting to what the spec's own
example URL shows.

**5. Consent request details** — `GET /api/hiecm/consent/v3/request/{consentRequestId}` (spec §6.17).
Same shape as one entry of #4's `requests` array, un-paginated. This is what a "view this request"
screen calls, and — see #6 below — what supplies the data to pre-fill an approval.

**6. Approve** — `POST /api/hiecm/consent/v3/request/{consentRequestId}/approve`. **NOT IN THE SPEC
PDF AT ALL — confirmed real via Postman only** (this is the endpoint Aayush pointed out; the earlier
draft of this chunk's research incorrectly reported it as missing before being corrected). Body:
```json
{
  "consents": [{
    "hiTypes": ["Prescription", "..."],
    "hip": { "id": "{{hip-id}}" },
    "careContexts": [{ "patientReference": "...", "careContextReference": "..." }],
    "permission": {
      "dateRange": { "to": "...", "from": "..." },
      "frequency": { "unit": "DAY", "value": 0, "repeats": 0 },
      "accessMode": "VIEW",
      "dataEraseAt": "..."
    }
  }]
}
```
**Design judgment call, flag it as such in the module banner**: approving is not a bare "yes" —
the patient submits back the SPECIFIC hip/careContexts/hiTypes/permission being granted. The most
sensible UX is: fetch #5 (request details) first, pre-fill the approve form from what it returned
(the HIP, care contexts, and hiTypes the request already named), let the patient review — and only
if you want to support narrowing, let them deselect some care contexts/hiTypes before submitting.
Build the pre-fill-from-details behavior; narrowing/editing is a nice-to-have, not required for this
chunk — say clearly in your report whether you built it or left it as full-acceptance-only.

**7. Deny** — `POST /api/hiecm/consent/v3/request/{consentRequestId}/deny` (spec §6.21). Body:
`{"reason": "..."}`. Spec's own words: "invoked from the PHR or mobile application."

**8. Revoke** — `POST /api/hiecm/consent/v3/revoke` (spec §6.22). Body: `{"consents": ["<consentId>",
...]}` — an ARRAY, so one call can revoke multiple artefacts at once. Spec's own words: "from the PHR
or mobile application." This acts on an already-GRANTED artefact, not a pending request — it's what
"my active consents" (#11 below) should offer per-row (or multi-select).

**9. Consent artefact details by request ID** — `GET /api/hiecm/consent/v3/artefact/request/
{consentRequestId}` (spec §6.18). The granted artefact(s) tied to one request — a request approved
against multiple HIPs produces multiple artefacts. Response is an array of `{"status", "consentDetail":
{...same shape as #5, plus "schemaVersion", "consentManager"}, "signature"}`.

**10. Consent artefact details by artefact ID** — `GET /api/hiecm/consent/v3/artefact/{consentId}`
(spec §6.19). Same per-item shape as #9, single artefact, not wrapped in an array per the spec's own
example (though double-check live — #9's example IS an array for what should conceptually be a
single-request's-worth of artefacts).

**11. All consent artefacts** — `GET /api/hiecm/consent/v3/artefact?limit=10&offset=0&status=ALL`
(spec §6.20). Your "active consents" screen: `{"size","limit","offset","consentArtefacts": [...same
per-item shape as #9/#10...]}`, paginated. This is where Revoke (#8) should be reachable from.

## What's explicitly NOT this chunk's job

- Consent request INIT (spec §6.4) and its on-init/notify callbacks (§6.5-6.8) — a HIU raises these,
  not a patient app; `repo/`'s own `server/hiu_consent.py` already implements the HIU side (see
  Verification below — this is actually useful to you, as the way to generate real test data).
- Consent request status + its on-status callback (§6.9-6.10) — HIU-side, not ours.
- Consent fetch (§6.11) — HIU-side.
- Reading the actual FHIR content behind a granted consent (§7 Data Flow) — separate, later phase.
- Any part of UIL (§10) — deferred to last, per Aayush's own instruction.
- Any change inside `repo/` — read-only reference, as always.

## Frontend — this earns its own screen, not an inline Home section

"View Linked Records" was small enough to live as one `<fieldset>` on `HomeScreen.tsx`. This is 11
endpoints covering a full list→detail→act→confirm lifecycle plus a separate artefacts list — too much
for one inline section without the page turning into a wall of forms. Suggested structure, matching
this project's existing conventions (a dedicated screen reachable from Home/nav, e.g.
`ConsentScreen.tsx`, following `ProfileScreen.tsx`'s expand/collapse-per-feature pattern internally):

1. A "Consent Requests" tab/section: list (#4) → tap a row → detail (#5) → Approve (#6) / Deny (#7)
   buttons right there, matching this project's real-app-nav standing rule (after approving/denying,
   return to a refreshed list, not a dead-end confirmation screen).
2. An "My Active Consents" tab/section: list (#11) → tap a row for full detail (#9 or #10) → Revoke
   (#8) reachable from there.
3. Auto-approve (#1/#2/#3) as a smaller, secondary settings-style section — this is a policy toggle,
   not something a patient interacts with per-request, so it doesn't need the same prominence.

A button/link from `HomeScreen.tsx` (or a nav entry, matching how `ProfileScreen.tsx` is already
reachable) should get the user here — don't leave it as an orphaned route.

## What to build

1. `aegle_phr/phr/consent.py` — all 11 functions, mirroring `links.py`'s `_headers()`/module
   structure closely (parameterize where the HTTP method/body/URL differ). Module banner should
   document: the approve-endpoint's spec-PDF-omission (and that Postman was the source), the
   approve-body design judgment call, and that every response shape here is unconfirmed until run
   live.
2. New routes in `aegle_phr/api.py`'s `build_app_api_router()`, one per function, plus whatever new
   Pydantic body/response types `schemas.py` needs (follow existing naming: e.g.
   `GetAllConsentRequestsBody`, `ApproveConsentRequestBody`, matching how `GetAllLinkedRecordsBody`
   names its `xToken` field even though it's sent as `X-AUTH-TOKEN` — same convention, keep it).
3. New functions in `testui/src/api/endpoints.ts` + types, following `getAllLinkedRecords()`'s
   pattern.
4. The frontend screen(s) described above, wired into navigation from `HomeScreen.tsx`.
5. Update `README.md`'s captured-shapes section with whatever ABDM actually returns for each of
   these 11 once tested live — this whole chunk is currently unconfirmed, so this is a meaningful
   chunk of real documentation to add, not a formality.

## Verification — and a real way to generate test data, not just live-test against nothing

Reads (#4, #5, #9, #10, #11) are side-effect-free — safe to test live immediately, same as
`links.py`. Actions (#1/#2/#3 auto-approve toggle, #6 approve, #7 deny, #8 revoke) change real state
on the ABDM sandbox — test these deliberately, not by spamming retries, same care as any
OTP-consuming P1 chunk even though nothing here sends an OTP.

**The practical problem**: you can't approve/deny/revoke a consent request that doesn't exist yet.
`repo/server/hiu_consent.py`'s `initiate_consent_request()` (and the CLI at
`repo/tools/m3_test_suite/flows/hiu_consent.py`) already implements the HIU side of raising a real
consent request — this is the tool to use to generate a real pending request against
`chordiaaayush1997@sbx` (or whichever ABHA address you're testing with) so this chunk's #4/#5/#6/#7
have something real to work against. Don't build a NEW way to raise test requests inside `aegle-phr`
— that's out of scope (see above); use what `repo/` already has, read-only, exactly as intended.

1. Offline first: routes wire up, requests build with the right host/headers/body shape, frontend
   round-trips against a mocked response.
2. Live reads (#4/#5/#9/#10/#11) as soon as offline checks pass — report the real response shape for
   each, since none are currently confirmed.
3. Before testing #1/#6/#7/#8 live: raise a real consent request via `repo/`'s HIU-side tooling
   first, confirm it shows up in #4's list, then test approve/deny/revoke against that real
   request/artefact. Report exactly what each real response looks like.

## Ground rules (standard, unchanged from every prior chunk)

- No throwaway scripts left behind in the repo.
- Deliver a detailed per-file change report, plus a short Cowork-pasteable summary at the end.
- Strict scope discipline: if you spot something else worth fixing, flag it, don't fix it — only
  fix bugs you introduce in this chunk.
- No git commit, push, or init.
- Never delete or truncate existing `logs/` or `storage/` content.
- Don't claim something works without actually running it.
- Flag any uncertainty visibly — especially the approve-body judgment call and any response shape
  that turns out to differ from what's documented above.
- Do not modify anything under `repo/` — read-only reference only, including its HIU-consent tooling
  used for test-data generation above.
- Never print the access key, client secret, plaintext OTP, mobile number, email address,
  password, or a live token into any report.
- Use `Authorization: Bearer <gateway token>` (never `apikey`) for the gateway credential, alongside
  `X-AUTH-TOKEN` for the session token this chunk's whole family needs.
