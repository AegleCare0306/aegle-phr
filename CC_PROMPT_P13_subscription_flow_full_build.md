# P13 — Subscription Flow (spec §8), full build: all 18 endpoints + Health Locker

Full build of spec §8 "Subscription Flow" (`ABHA_PHR_V3_Documents` v1.1, lines 2277-2746). Confirmed
via grep this window: **nothing is built** except two bare inbound-callback skeletons that only archive
the raw JSONB payload — no outbound calls, no UI, no real per-callback logic. This is a brand-new
subsystem, not a patch on existing code.

## Recommended model
Sonnet, extended thinking **ON** — same class of work as P8-P12 (Consent Manager, self-view auto-approve):
this touches an authorization-adjacent, registration-adjacent flow (Setup Locker registers a
`X-LOCKER-ID` we've never used anywhere else in this project — see "Open item / R2" below), has several
easy-to-conflate callback URLs (see the URL table), and a genuine spec-vs-Postman discrepancy to resolve
carefully rather than guess past.

## Why this app plays BOTH roles here — read this before writing any code
Spec §8.1: *"Health locker/PHR should initiate subscription requests so that it receives
notifications/alerts whenever new information is available"* for two categories — `LINK` (a new care
context got linked at some HIP) and `DATA` (new data landed on an already-linked care context) — and
*"Subscription will get auto approve for health locker for all HIPs and for all HI types."*

Every endpoint in §8 that says "invoked by the patient/user through the PHR application" means **our own
app's UI**, not a third-party reference app — this project *is* the PHR application the spec keeps
referring to. So:
- When OUR app is the *requester* of the subscription (subscribing to be notified about a patient's own
  new data — the self-view-shaped case), it identifies itself with `hiu.id = CLIENT_ID`
  (`server.config.CLIENT_ID`, `"SBXID_046112"`) — same convention already confirmed three separate ways
  this project (established pattern, ABDM's own doc note, and Postman's own template variable name for
  this exact field is literally `{{healthlocker id/PHR id}}`). Per 8.1, ABDM auto-approves this case, so
  no patient action is needed — a GRANTED callback should arrive directly.
- When OUR app is the *patient-facing surface* where a patient takes action on a subscription (approve /
  deny / edit — 8.3.4/8.3.7/8.3.9), that's a UI screen in this app, calling out to ABDM on the patient's
  behalf. Build this regardless of the auto-approve default above — the spec documents it as a real,
  callable capability, and auto-approve is a policy that could be off, fail, or not cover every case.

## URL table — read carefully, several of these look alike but are NOT the same endpoint
All `/api/hiecm/...` URLs are `{abdm_hiecm_base_url}/...`. All `{{callback}}/...` URLs are OUR inbound
routes, under `aegle_phr/callbacks/`.

Outbound (this app calls ABDM):
| # | What | Method | URL |
|---|---|---|---|
| 8.3.2 | Init subscription request | POST | `/api/hiecm/subscription-requests/v3/init` |
| 8.3.6 | Ack HIU received on-init callback | POST | `/api/hiecm/subscription-requests/v3/hiu/on-notify` |
| 8.3.4 | Approve subscription request | POST | `/api/hiecm/subscription-requests/v3/{subscription_requestid}/approve` |
| 8.3.7 | Deny subscription request | POST | `/api/hiecm/subscriptionrequests/v3/{subscription_id}/deny` (note: no hyphen in `subscriptionrequests` here — this is exactly as printed in the spec, verify against a live 404 before assuming it's a typo) |
| 8.3.9 | Edit subscription | PUT | `/api/hiecm/subscription-requests/v3/patients/{approved_subscription_id}` |
| 8.3.12 | Ack HIU received care-context notify | POST | `/api/hiecm/subscription-requests/v3/hiu/care-context/on-notify` |
| 8.3.1 | Get all subscription requests | GET | `/api/hiecm/subscription-requests/v3/requests` |
| 8.3.13 | Subscription details by REQUEST id | GET | `/api/hiecm/subscription-requests/v3/request/{subscriptionRequestId}` |
| 8.3.14 | Subscription details by SUBSCRIPTION id | GET | **see discrepancy note below** |
| 8.3.15 | Get all subscription+consent requests | GET | `/api/hiecm/subscription-requests/v3/patients/requests` (query: `consentLimit`, `consentOffset`, `subscriptionLimit`, `subscriptionOffset`, `status`) |
| 8.3.16 | Get patient's subscribed lockers | GET | `/api/hiecm/subscription-requests/v3/patients/lockers` (query: `includeInactive`) |
| 8.3.17 | Locker details by locker id | GET | `/api/hiecm/subscription-requests/v3/patients/lockers/{locker-id}` |
| 8.3.18 | Setup Locker | POST | `/api/hiecm/subscription-requests/v3/setup-locker` |
| — | Disable subscription (Postman-only, no spec number — see below) | POST | `/api/hiecm/subscription-requests/v3/disable/{subscriptionID}` |
| — | Enable subscription (Postman-only, no spec number — see below) | POST | `/api/hiecm/subscription-requests/v3/enable/{subscriptionID}` |

Inbound (ABDM calls us):
| # | What | URL | Status |
|---|---|---|---|
| 8.3.3 | on-init callback | `/api/v3/hiu/hiecm/subscription-requests/on-init` | **Already routed** — archive-only skeleton in `CALLBACK_ROUTES` as `subscription_on_init`. Needs real logic added. |
| 8.3.5 / 8.3.8 / 8.3.10 | approve/deny/edit-result notify (all three share ONE URL, distinguished by `status` in the body: `GRANTED`/`DENIED`/`REVOKE` — spec's own examples are inconsistent about the exact enum, log whatever value actually arrives) | `/api/v3/hiu/subscription-requests/hiu/notify` | **Already routed** — archive-only skeleton as `subscription_notify`. Needs real logic added. |
| 8.3.11 | care-context event notify ("new LINK/DATA available") | `/api/v3/hiu/subscription/notify` | **NOT currently routed anywhere.** This is a *different* path from the one above (`subscription/notify` vs `subscription-requests/hiu/notify`) — do not conflate them. Must be added as a new entry in `CALLBACK_ROUTES`. |

### Discrepancy to resolve, don't guess past it (8.3.14 vs Postman)
The spec text for 8.3.14 (line 2662) prints the URL as `/api/hiecm/subscription-requests/v3/request/{subscriptionId}`
— **identical** to 8.3.13's URL directly above it, which is almost certainly a copy-paste error in the
spec (two different endpoints for two different lookup keys shouldn't share one path). This project's own
"PHR" Postman collection's "subscription-details-by-subscription-id" request uses a different, plausible
path: `/api/hiecm/subscription-requests/v3/{subscriptionID}` (no `/request/` segment). Use Postman's URL
for 8.3.14, keep spec's URL for 8.3.13, and note this choice in a code comment so it's easy to correct
later if a live call proves it wrong.

### Disable/Enable — not in the spec's 18 numbered items, but in Postman
Postman's "Subscription and Health locker" folder has two more requests the spec text never numbers:
`subscription-disable` (`POST .../v3/disable/{subscriptionID}`) and `subscription-enable`
(`POST .../v3/enable/{subscriptionID}`). Per this project's standing practice (cross-reference Postman
before treating anything as spec-undocumented, and build what Postman confirms even if the spec prose
missed it), implement these two as well — same header convention, no request body evident in the saved
Postman example (empty body is fine, confirm against a live 4xx/2xx rather than guessing a body shape).

## What to build

### 1. New module `aegle_phr/phr/subscription.py` (mirror `consent.py`'s shape and header-building helper)
One function per outbound call above (8.3.2, 8.3.4, 8.3.6, 8.3.7, 8.3.9, 8.3.12, 8.3.1, 8.3.13, 8.3.14,
8.3.15, 8.3.16, 8.3.17, 8.3.18, plus disable/enable) — same `AbdmResult` return shape, same
`Authorization: Bearer {get_gateway_token()}` + `X-AUTH-TOKEN` + `X-CM-ID` + REQUEST-ID/TIMESTAMP header
pattern already used everywhere in `consent.py`/`data_flow.py`. Exact body/query shapes are in the spec
excerpt above (8.3.2's full request body, 8.3.4's full request body with `includedSources`/
`excludedSources`, etc.) — use those verbatim, they're taken directly from the spec PDF.

**8.3.18 Setup Locker** needs a new header this project has never sent before: `X-LOCKER-ID`. Don't
invent a value — see "Open item / R2" below for what to pass and how to treat failure.

### 2. Extend the two existing callback skeletons + add the missing third route
`aegle_phr/callbacks/dispatcher.py`'s `dispatch()` is a single generic archive-and-log function used by
all six current callback types, with a "never raises" contract stated in its own docstring — **keep that
contract intact**. Don't put real business logic inside `dispatch()` itself. Instead, follow the same
shape `repo/`'s M3 code already uses for its own callbacks (`repo/server/callbacks/services/*.py`, one
service function per callback type, dispatched by `callback_type` after archival): add a small
`aegle_phr/callbacks/subscription_services.py` with one function per callback type below, call it from
`aegle_phr/callbacks/router.py`'s handler (or from `dispatch()` via an optional post-archive hook — your
call on the cleanest wiring, but the archive must still happen unconditionally and no real-logic
exception may propagate past the callback route) for exactly these `callback_type`s:
- `subscription_on_init` (8.3.3): correlate the callback's `response.requestId` back to the pending
  subscription-request row (mirror how `consent_init_on_init_service.py` correlates 6.5's callback), then
  call 8.3.6 (`.../hiu/on-notify`) to ack receipt — same request/response/ack shape as consent's 6.5→6.7.
- `subscription_notify` (8.3.5/8.3.8/8.3.10, one shared URL): branch on the body's `status`
  (`GRANTED`/`DENIED`/whatever value actually arrives for an edit) and update the subscription's stored
  status accordingly — mirror `consent_hiu_notify_service.py`'s shape (that file already handles an
  analogous multi-outcome single-URL callback for consent).
- **New**: `subscription_care_context_notify` (8.3.11, `/api/v3/hiu/subscription/notify` — add this path
  to `CALLBACK_ROUTES` in `router.py`, it is not currently registered anywhere and is not in
  `FORBIDDEN_PATHS` either). On receipt: ack via 8.3.12 (`.../hiu/care-context/on-notify`), then apply
  §8.1's own stated next step for the category in the event body — `LINK` means *"Health locker/PHR
  should initiate a consent request for the notified care context"* (reuse the existing consent-init path
  from P8/P9, not a new one), `DATA` means *"check if any existing consent request is available... and
  use the same to initiate the data-request"* (reuse the existing 7.3.1 data-flow-request path). Wire
  this as a real trigger, not just a log line — that's the entire point of subscribing in the first place
  (§8.1: *"so that it receives notifications/alerts"*), but keep it defensive: if no matching consent
  exists yet for a `DATA` event, don't crash, log it as an open item on that event instead of silently
  dropping it.

### 3. Patient-facing UI — real navigation, not a bolt-on page
Standing UX directive: this needs to be reachable through the app's real navigation, the same way the
Requests tab (P8) and Data Flow views are — not a hidden or dev-only route. Add a "Subscriptions" (or
similar — match this app's existing naming conventions in its nav) section showing:
- current subscriptions and their status (via 8.3.1/8.3.13/8.3.14/8.3.15),
- pending ones needing patient action, with Approve/Deny/Edit controls (8.3.4/8.3.7/8.3.9) — mirror the
  existing consent Requests tab's picker UI/UX pattern from P8 rather than inventing a new one,
- linked Health Lockers (8.3.16/8.3.17) and a way to trigger Setup Locker (8.3.18) — surface whatever
  `X-LOCKER-ID` ends up being used (see below) so it's visible for debugging, not just fired blind.

### 4. Self-subscription bootstrap (the auto-approve-shaped case)
Mirror `data_flow.py::ensure_self_view_auto_approve()`'s existing pattern: add an
`ensure_self_subscription()` (or similar name, match this app's conventions) that calls 8.3.2 with
`hiu.id = CLIENT_ID`, `patient.id` = the current patient's ABHA address, `categories: ["LINK", "DATA"]`,
covering all HIPs (`isApplicableForAllHIPs`-style scope, per 8.1's auto-approve description). Call it from
wherever `ensure_self_view_auto_approve()` is already invoked in this app's flow, so the two self-service
policies (consent auto-approve, subscription) get set up together. Log the outcome clearly (2xx, or exact
error) — don't assume auto-approve fires cleanly on the first attempt without checking.

## Open item / R2 — Health Locker registration, resolve by testing live, not by blocking
Whether `SBXID_046112` (this app's `CLIENT_ID`) is registered with ABDM as a `HEALTH_LOCKER` type (not
just HIU/HIP) is unconfirmed — this was flagged as R2 earlier and never independently resolved. Per
Aayush's own instruction, don't treat this as a blocking prerequisite: build Setup Locker (8.3.18) for
real, try `X-LOCKER-ID` = `CLIENT_ID` first (same identity-reuse convention as everything else in this
app), and if that 4xxs, try `X-LOCKER-ID` = a freshly-generated locker id string (spec's example value is
just `"X-LOCKER-ID"` literally — unhelpful — but 8.3.16's response shape shows `lockerId: "HIU_V3"`,
suggesting it may be a caller-chosen string, not something ABDM assigns back). **Log the exact request and
response for whichever attempt is made** so Aayush can tell definitively whether registration is the
blocker, without needing a separate diagnostic round-trip.

## Constraints (standing, unchanged)
- Do not modify any file under `repo/` — only import/call its existing code if genuinely needed
  (shouldn't be, this is a self-contained new subsystem in `aegle_phr/`).
- Never delete or truncate existing `logs/`/`storage/` content.
- Use `Authorization: Bearer <gateway token>` everywhere — never `apikey`.
- Never print secrets/tokens into logs or any report back.

## Verification
1. Confirm the new route (`/api/v3/hiu/subscription/notify`) is registered and NOT one of the 4
   `FORBIDDEN_PATHS` (it isn't — those are all consent/health-information paths) and doesn't collide with
   anything `repo/` owns.
2. Trigger `ensure_self_subscription()` for a real patient session; report the exact status/body of the
   8.3.2 call, and whether a `subscription_on_init` callback actually lands and gets ack'd (8.3.6) shortly
   after — real end-to-end proof, not just the initiating call succeeding.
3. Confirm the resulting subscription resolves to GRANTED (via 8.3.13/8.3.14, or the on-notify callback)
   without requiring manual patient action — that's the whole premise of §8.1's auto-approve claim; if it
   does NOT auto-resolve, report that plainly rather than treating it as done.
4. Attempt Setup Locker (8.3.18) at least once, report the exact request/response either way (success or
   the specific error), per the R2 note above.
5. Confirm the Subscriptions UI is reachable from the app's real navigation (screenshot or equivalent),
   not just a route that responds to a direct URL.
