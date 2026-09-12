# P11 — Self-view still fails after P10: our own PATRQT requests are never approved at all

## Recommended model
Sonnet, extended thinking **ON**. This sets up a standing pre-authorization policy at ABDM
(auto-approval for future consent requests) — an authorization-boundary change, same standing
policy as P9/P10.

## Why P10 wasn't enough (confirmed against live storage, not guessed)

P10 shipped and IS working exactly as designed — confirmed via `repo/storage/pending_consent_requests.jsonl`:
Pooja's account (`poojaanchaliya@sbx`) at HIP `IN3310002215` now has **six separate** self-view
consent-request-init calls on record today (consent_request_ids `84c8e125…`, `5b5a7e15…`,
`0fbf720e…`, `a5fcdcd9…`, `0a66aaae…`, `9fbd574b…`), one per login/retrigger. P10's "don't trust a
foreign GRANTED artefact as coverage" fix is correctly causing our own request to fire every time.

**But not one of those six requests ever resolved.** `repo/storage/consents.jsonl` (the HIP-side
consent-notify store — populated whenever ABDM notifies a status change) has exactly **three** rows
for `poojaanchaliya@sbx`, and none of their keys match any of the six request IDs above. ABDM never
notified GRANTED for any of our own self-raised requests — they're just sitting there, presumably in
`REQUESTED` state, waiting on the same manual per-request patient approval P8's picker was built for
but that nothing in the self-view flow ever exercises. That's the actual reason it "still doesn't
work": not a wrong architecture, not a registration-type problem — our own requests are never being
approved, by anyone, ever.

## The real mechanism ABDM's own sandbox app uses (confirmed via a live-captured Postman example,
not the spec PDF, which documents a different, apparently-unconfirmed endpoint — see below)

ABDM has a genuine standing-policy feature, **Consent Auto-Approval**, that is a real 3-call sequence
under a `/cm/...`-prefixed host, patient-PIN-gated:

1. `POST https://dev.abdm.gov.in/cm/patients/pin` — header `X-AUTH-TOKEN` (patient session token),
   body `{"pin": "1111"}` → `204`. One-time: sets the patient's Consent PIN if they don't have one.
2. `POST https://dev.abdm.gov.in/cm/patients/verify-pin` — header `X-AUTH-TOKEN`, body
   `{"pin": "1111", "requestId": "<uuid>", "scope": "consent.autoapprove"}` → `200`, body
   `{"temporaryToken": "<jwt>"}`.
3. `POST https://dev.abdm.gov.in/cm/consents/auto-approve` — headers `Authorization` (our own gateway
   bearer token), `X-Auth-Token: <temporaryToken from step 2>` (**not** the raw patient session
   token), `x-cm-Id: sbx`, body:
   ```json
   {
     "isApplicableForAllHIPs": true,
     "hiu": {"id": "HIU_007", "name": "Keeladi hospital"},
     "includedSources": [{
       "hiTypes": ["DiagnosticReport","Prescription","DischargeSummary","OPConsultation","ImmunizationRecord","WellnessRecord","HealthDocumentRecord"],
       "purpose": {"code": "PATRQT", "text": "Self Requested"},
       "period": {"from": "2020-11-01T12:54:21.896Z", "to": "2029-11-04T12:54:21.896Z"}
     }],
     "excludedSources": []
   }
   ```
   → `200`, body `{"autoApprovalId": "<uuid>"}`. This is a real, captured example response, not an
   inferred shape — confirmed via Postman's "ABDM Collection" → "Building PHR App" → "Setup
   Subscriptions"/"Setup Auto-approval" folder.

Once this policy exists for a patient (scoped to our own `hiu.id` + `purpose.code: PATRQT` + a
`hiTypes`/date-range envelope), ABDM auto-grants any *future* matching self-view request the instant
it's raised — no per-request manual approval, no picker, nothing. This is almost certainly what ABDM's
own sandbox app does once, early, per patient — not a different actor type, not a Health Locker
registration, not a different data-fetch mechanism. (I did look hard at whether being registered as a
"Health Locker/PHR" via spec §8's Subscription Flow was the real difference — read that section in
full, found real evidence a distinct actor type exists in ABDM's model — but found no evidence it's
what's actually blocking us, and the auto-approve gap above is a complete, sufficient, directly-evidenced
explanation on its own. Don't chase the Health Locker angle unless this fix, once live-tested, turns
out not to be enough.)

## The code already exists for auto-approve — but it's wrong, and was never wired in

`aegle_phr/phr/consent.py::auto_approve()` (routed at `POST /phr/consent/auto-approve`, already has a
frontend button in `ConsentScreen.tsx`) implements spec §6.13's *documented* endpoint:
`POST {abdm_hiecm_base_url}/consent/v3/auto/approve` = `https://dev.abdm.gov.in/api/hiecm/consent/v3/auto/approve`,
sending the patient's raw session token directly as `X-AUTH-TOKEN`. Its own docstring already flags
this honestly: *"UNCONFIRMED against a live capture."* It's correct to flag it that way — that URL and
header shape do not match the real, captured, working example above at all (different host+path
entirely: `/cm/consents/auto-approve`, not `/api/hiecm/consent/v3/auto/approve`; a `temporaryToken`
from a PIN-verify step, not the raw session token). And separately, regardless of which shape is
right, **nothing in `HomeScreen.tsx`'s self-view flow ever calls it** — it only exists today as a
manual test button. Both problems need fixing.

## The fix — three parts

**Part 1 — add the missing base URL.** No existing settings field points at `https://dev.abdm.gov.in/cm`
(the three existing ones are `abdm_gateway_base_url` = `.../api/hiecm/gateway/v3`, `abdm_hiecm_base_url`
= `.../api/hiecm`, `abdm_abha_base_url` = `abhasbx.abdm.gov.in/abha/api/v3`). Add a new
`abdm_cm_base_url` setting (default `https://dev.abdm.gov.in/cm`), same pattern as the other three
(`.env` + `.env.example` + `Settings` field in `aegle_phr/settings.py`).

**Part 2 — implement the real 3-call sequence**, replacing (not just adding alongside) the current
`auto_approve()`:
- `create_consent_pin(settings, x_auth_token, pin) -> AbdmResult` — `POST {abdm_cm_base_url}/patients/pin`,
  header `X-AUTH-TOKEN`, body `{"pin": pin}`. Treat any non-2xx here as "PIN probably already exists,
  continue" rather than a hard failure — a fixed dummy PIN (e.g. `"1111"`, matching the Postman
  example, consistent with this whole project's dummy-data conventions) only needs to be set once per
  patient and ABDM will reject re-setting it; don't let that abort the flow.
- `verify_consent_pin(settings, x_auth_token, pin) -> AbdmResult` — `POST {abdm_cm_base_url}/patients/verify-pin`,
  header `X-AUTH-TOKEN`, body `{"pin": pin, "requestId": <new uuid4>, "scope": "consent.autoapprove"}`,
  returns the `temporaryToken` this flow needs next.
- Rewrite `auto_approve()` to hit `POST {abdm_cm_base_url}/consents/auto-approve` with headers
  `Authorization` (this project's own existing gateway-bearer-token helper — check how
  `providers.py`/`links.py` source theirs, reuse the same one, never hardcode/duplicate token logic),
  `X-Auth-Token: <temporaryToken>`, `x-cm-Id: <settings.abdm_x_cm_id>`. Body shape is unchanged from
  today's implementation (`isApplicableForAllHIPs`, `hiu`, `includedSources`, `excludedSources`) — just
  the URL and the `X-Auth-Token` value are wrong today.
- **`hiu.id` in this payload MUST be the exact same value `request_self_view_consent()` uses when it
  raises the actual self-view request** (today: `HIPS[0]["hip_id"]` from `repo`'s live config) — ABDM's
  auto-approval matching is presumably by requester identity, and a mismatch here would silently make
  the whole policy useless. Same care for `hiTypes`/date-range coverage: the policy's `period`/`hiTypes`
  should be at least as broad as anything `request_self_view_consent()` will ever request (that
  function's own hiTypes/date-range parameters are caller-supplied — make sure whatever calls it for
  self-view provisioning stays within what the policy covers, or widen the policy to the same
  effectively-unbounded span the Postman example uses).

**Part 3 — wire this into the self-view flow, once per patient, before the first self-view request is
ever raised.** The natural point is `HomeScreen.tsx`'s P9/P10 self-view effect: before calling
`requestSelfViewConsent(...)` for a HIP that needs it, ensure the auto-approval policy has been set up
for this patient this session (a simple session-scoped flag/ref is enough — don't call
create-pin/verify-pin/auto-approve on every render or every HIP, just once per login). If the
auto-approve setup call itself fails, don't block the existing P8 manual-picker fallback — self-view
should degrade to "raise the request, patient approves manually via the picker" the same way it does
today, not hard-fail.

## What's explicitly NOT in scope
- No change to P9/P10's own logic (coverage-check, known-bad-consent tracking) — that's correct and
  proven; this is purely about making sure a raised request actually gets approved.
- No change to `repo/`.
- Don't build a UI for the patient to choose/change their own consent PIN — a fixed sandbox-only dummy
  PIN is fine for this test app, same spirit as the rest of this project's dummy fixtures.

## Verification (Aayush will run this live — report the actual observed outcome)
1. Confirm, via the server log, that the new 3-call sequence (`/cm/patients/pin` → `/cm/patients/verify-pin`
   → `/cm/consents/auto-approve`) actually fires and each call returns 2xx for a fresh patient login —
   the create-pin step in particular, since it's the one most likely to already be set from a prior run.
2. Use a HIP this account has NOT already self-view-requested before today's mess of six pending
   requests (or manually clear/ignore those old ones) — confirm a NEW self-view request raised after
   the auto-approve policy is set up actually shows up GRANTED (check `repo/storage/consents.jsonl`
   for a new row keyed by that new request's consent id) within the existing poll window, not stuck
   pending like today's six.
3. Once GRANTED, confirm `pullRecords()` actually succeeds end-to-end for that HIP in `aegle-phr` (not
   just ABDM's own sandbox app) — the original symptom Aayush reported.
4. If the auto-approve policy does NOT actually cause the new request to auto-grant (i.e. this
   hypothesis turns out wrong, or the `hiu.id`/hiTypes/period matching doesn't line up the way this
   prompt assumes), report exactly what happened instead — don't assume success.
