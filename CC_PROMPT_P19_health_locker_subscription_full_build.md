# CC Prompt P19 — Health Locker + Subscription: full build, and remove every earlier workaround

**Recommended model: Opus, extended thinking ON.** This chunk rewires how a patient's own records reach the
app. It deletes the earlier self-view machinery and replaces it with the Health Locker path, across
`aegle-phr` and a small, additive part of `repo/`, right at the consent/authorization boundary every other
flow depends on. A subtle mistake here is expensive to find later, which is this project's own threshold
for Opus over Sonnet.

This prompt **supersedes** the subscription parts of `CC_PROMPT_P13_subscription_flow_full_build.md` and all of
`CC_PROMPT_P18_health_locker_subscription_reset.md`. Reuse any working code from either. Don't treat their
design as correct just because it exists.

---

## 1. What changed, and why this chunk exists

Aayush's own words, 2026-09-22:

> *"I have been able to successfully register one of our facilities as a Health Locker and added that locker
> for a patient."*
>
> *"Our Health Locker is the Aegle Urgent Care facility."*
>
> *"Let's create a prompt to implement the subscription feature all at once. We should implement all —
> approve, deny, edit etc."*
>
> *"Make sure all the previous workarounds we implemented are removed/deleted from the code — like reading
> SBX_001 ID and getting all records. Everything should happen using this new logic. No workaround should
> remain."*

So, concretely:

- The **Aegle Urgent Care** facility is now registered with ABDM as a Health Locker. **Its locker ID is
  `IN2410002590`**, confirmed by Aayush from the set-up patient's locker list (8.3.16 returned
  `"lockerId": "IN2410002590", "lockerName": "Aegle Urgent Care"`). He registered it through Postman's Gateway
  `PUT /api/hiecm/gateway/v3/bridge-service`, with body `isHip: true, isHiu: true, isHealthLocker: true,
  isPhr: true`. No code in either repo made that call.
- **The same facility is also one of our four HIPs** (`IN2410002590` is in `repo/server/config.py`'s `HIPS`
  list). It now plays both sides: a hospital that holds records, and the locker that collects them. Keep that
  in mind in 3.5 and in the live tests.
- For patient `poojaanchaliya@sbx` (ABHA number 91-4665-3075-0069), he has run **Setup Locker**
  (`POST /api/hiecm/subscription-requests/v3/setup-locker`, `X-LOCKER-ID: IN2410002590`). **The live response
  was not what the spec documents:**
  ```json
  { "subscriptionId": "1a6476b0-1bb2-4e42-b1fc-33180b75ce92",
    "consentAutoApprovalId": "380a0096-d684-452a-b3e0-e5ee2768401a" }
  ```
  The spec shows only `consentAutoApprovalId`. In the spec, a `subscriptionId` only exists once a subscription
  is **granted**. So one patient-side Setup Locker call evidently creates **both** the locker's subscription
  (already granted) **and** its consent auto-approval policy. `patient-subscribed-lockers` then returned the
  locker active (`id 15044`, `dateCreated 2026-09-22T10:49:39.360Z`, `isActive: true`), plus an undocumented
  `healthIdNumber` field. The design below is built on this live result, not on the spec's example.
- **What that subscription is**, from `patient-requests` (8.3.15) for the same patient, verbatim:
  ```json
  { "subscriptionId": "1a6476b0-1bb2-4e42-b1fc-33180b75ce92",
    "requestId": "37519bb9-135a-4116-b435-4c1c04676ac0",
    "createdAt": "2026-09-22T10:49:39.191Z", "lastUpdated": "2026-09-22T10:49:39.248Z",
    "purpose": { "text": "Self Requested", "code": "PATRQT", "refUri": "www.abdm.gov.in" },
    "patient": { "id": "poojaanchaliya@sbx" },
    "hiu": { "id": "IN2410002590", "name": "Aegle Urgent Care", "type": "PATIENT" },
    "hips": [], "categories": ["DATA", "LINK"],
    "period": { "from": "2026-09-22T10:50:38.333Z", "to": "2126-09-22T10:49:38.333Z" },
    "status": "GRANTED", "requesterType": "HEALTH_LOCKER" }
  ```
  What this settles:
  - It was **granted automatically**, 57 ms after creation, with no approve step.
  - It covers **every hospital** (`hips: []`) and **both categories**.
  - It runs **100 years**, so expiry is not a practical concern.
  - Its purpose is **`PATRQT`**, not the `CAREMGT` that the spec's and Postman's init examples use.
  - The locker acts as the patient's own agent: `hiu.type: "PATIENT"`, `requesterType: "HEALTH_LOCKER"`.
- **The same response shows a second, foreign subscription**: `subscriptionId 40220183-49b9-419c-91f0-e4678213c6c2`,
  `hiu: { id: "sbx_001", name: "Sanbox Test Hospital", type: "PATIENT" }`, `requesterType: "HIU"`, purpose
  `PATRQT`, granted 2026-09-02. **`sbx_001` is ABDM's own sandbox PHR app.** This is the "SBX_001" in Aayush's
  instruction, and the old workaround read from it (section 5). It belongs to another app: our automation must
  **only ever consider subscriptions whose `hiu.id` is our locker ID**, and must never read, reuse or act on
  `sbx_001`'s. (The patient may still see it in their own Subscriptions screen, since it's theirs, clearly
  labelled as another app's.)
- The same call's `consents` block came back as `"size": 0, "requests": [ {} ]`: a list holding **one empty
  object** when there are no items. Treat items with no ID as absent, everywhere lists are parsed.
- The earlier Subscription attempts (3 Sep) all returned HTTP 400. They were made **before** the locker was
  registered, using `hiu.id = CLIENT_ID (SBXID_046112)` and the four HIP ids. That evidence is now stale.

**The new logic for how a patient's own records reach the app, and the only logic allowed to remain after this
chunk:**

> Patient opts in once → the patient adds the Aegle Urgent Care locker (Setup Locker), which in one call creates
> the locker's granted subscription **and** its consent auto-approval policy → ABDM sends the locker LINK/DATA
> alerts → for each alert the locker gets a consent as the locker (auto-approved via the locker's policy, or
> approved by the patient) → the locker requests the data → the records are stored and shown to the patient.

The HIU-initiated subscription route (8.3.2 init → `on-init` → approve) is still implemented in full, with
UI, because Aayush wants every Subscription API built. But it is **not** part of the locker's automatic path,
except as the recovery route described in 3.5, if the live tests show it's needed.

Anything else that obtains a patient's records, or consent to them, is a workaround and goes (section 5).

---

## 2. Step 0 — verify the current state before changing anything

Aayush works directly in Claude Code between Cowork sessions. The inventory below is Cowork's last verified
view (12 Sep), and it may already be stale. Check each point against the actual code, and report what differs
before building on it.

**Last verified view (12 Sep):**
- `aegle_phr/phr/subscription.py` — 15 public functions from P13 (init, ack-on-init, approve, deny, edit,
  ack-care-context-notify, get-all, details by request id, details by subscription id, patient requests, patient
  lockers, locker details, setup-locker, disable, enable), plus `_execute()` and two header builders
  (requester-side without `X-AUTH-TOKEN`, patient-side with it). `_execute()` logs only the HTTP status to the
  plain-text log; response bodies go only to Postgres `abdm_call_log`.
- `aegle_phr/callbacks/subscription_services.py` — handlers for `subscription_on_init`, `subscription_notify`,
  `subscription_care_context_notify`, wired in `aegle_phr/callbacks/router.py`'s `_SUBSCRIPTION_HANDLERS`.
- `aegle_phr/phr/subscription_repository.py` + `SubscriptionRequest` model (`subscription_request` table).
- `aegle_phr/api.py` — `/phr/subscription/*` routes: approve, deny, details-by-request-id,
  details-by-subscription-id, disable, edit, enable, ensure-self-subscription, get-local, lockers/get-all,
  lockers/get-one, patients/requests, requests/get-all, setup-locker.
- `testui/src/routes/SubscriptionsScreen.tsx` — includes a Setup Locker button with a free-text `X-LOCKER-ID` field.
- `aegle_phr/phr/data_flow.py` — `request_self_view_consent`, `ensure_self_view_auto_approve`,
  `ensure_self_subscription`, `discover_self_view_consents`, `trigger_consent_fetch`,
  `request_health_information`, `get_health_information_status`.
- P18 was delivered on 9 Sep but had not run as of 12 Sep. **Check whether it has run since** (new flows in
  `repo/tools/m2_test_suite/flows/bridge_gateway.py`, response-body logging in `subscription._execute()`). Keep
  whatever of it is useful, and say so.

**Resolve these facts. Stop and report if any turns out differently than expected:**

1. **The locker's service ID — already known: `IN2410002590`.** This is the value that goes in `X-LOCKER-ID`
   and `hiu.id`. Still confirm read-only that `GET /api/hiecm/gateway/v3/bridge-services` lists
   `IN2410002590` with the Health Locker type, and report the exact types and flags it shows. Store it as a
   new setting (e.g. `abdm_health_locker_id=IN2410002590` in `aegle_phr/settings.py` + `.env`), never
   hardcoded.
2. **Which client ID owns the locker service.** If it sits under `CLIENT_ID` (`SBXID_046112`), the unused
   `PHR_CLIENT_ID=SBXID_073333` pair in `repo/.env` + `repo/server/config.py` is a dead leftover and goes (section 5).
   **If the locker sits under `PHR_CLIENT_ID` instead, stop and report.** Every locker-side call would then need
   that client's gateway token, and the design below changes.
3. **What Setup Locker actually created for `poojaanchaliya@sbx`.** Read-only calls, as that patient:
   - `GET /api/hiecm/subscription-requests/v3/patients/lockers/IN2410002590` (8.3.17). Report the
     `subscriptions[]` and `autoApprovals[]` in full. For the auto-approval policy that means
     `isApplicableForAllHIPs`, `hiu`, `includedSources` (hiTypes, **purpose code**, period),
     `excludedSources` and `isActive`. The consent requests the locker raises must match this policy exactly
     (same HIU id, a purpose code and HI types it covers, a date range inside its period), or they won't
     auto-approve.
   - `GET /api/hiecm/subscription-requests/v3/1a6476b0-1bb2-4e42-b1fc-33180b75ce92` (8.3.14). Most of the
     subscription is already known from 8.3.15 (section 1). This call confirms the details-by-subscription-id
     path works, and shows the `includedSources` (HI types per source) that 8.3.15 doesn't.
   The auto-approval policy's **purpose code** matters most. The subscription is `PATRQT`, so the policy very
   likely is too, but confirm it. Build to what these return, not to an assumption.
4. **Whether ABDM sent any callbacks when Setup Locker ran.** Search `aegle-phr`'s `callback_log` (and `repo/`'s
   `storage/api_capture/` and `storage/callbacks/`) for anything received around `2026-09-22T10:49:39Z`, in
   particular a `hiu/notify` for the new subscription (`x-hiu-id: IN2410002590`). Report what arrived, redacted,
   or that nothing did. Whether the app must wait for a callback or can trust Setup Locker's response depends
   on this.

---

## 3. What to build

Reuse the existing modules above wherever they work. Fix every call against **Appendix A**. That appendix is
the result of a full cross-check of spec §8 against the PHR Postman collection. Where the two disagree, the
appendix says which one to follow, and why.

### 3.1 Every Subscription / Health Locker call, correct

All 13 outbound spec calls, all 5 inbound callbacks and the two Postman-only calls (disable / enable) must be
implemented and correct per Appendix A. Known problems to check for in the P13 code:
- **The acknowledgement sequence.** Spec §8.2's sequence diagrams show: init → `on-init` callback, with *no*
  acknowledgement after `on-init`. `hiu/on-notify` (8.3.6) acknowledges the **decision** callback
  (`hiu/notify`: approved / denied / edited), not `on-init`. If P13 sends 8.3.6 after `on-init`, that is wrong;
  move it.
- **Deny takes the subscription request ID**, not a subscription ID.
- **Details by subscription ID** uses `/v3/{subscriptionId}`. The spec's printed URL is a copy of 8.3.13's.
- **List and inbox parameters** are query parameters, not headers or a body.
- **Locker-side calls send no `X-AUTH-TOKEN`.** That covers init, 8.3.6 and 8.3.12, per Postman.
- **Diagnosability.** Every Subscription/Locker call also writes a truncated, **secret-redacted** response-body
  line to the plain-text log, through `aegle_phr/phr/redaction.py`. Status-code-only logging has already blocked
  diagnosis once, because Cowork cannot reach Postgres.

### 3.2 Callbacks

Three inbound paths, all already routed (verify):
- `/api/v3/hiu/hiecm/subscription-requests/on-init` → save `subscriptionRequest.id` against the pending row,
  matched by `response.requestId`.
- `/api/v3/hiu/subscription-requests/hiu/notify` → one URL for approved / denied / edited; branch on
  `notification.status`. On GRANTED, store `subscription.id`, the sources and the period. Then acknowledge with
  8.3.6 (`acknowledgement.subscriptionRequestId`, and `response.requestId` = this callback's own `REQUEST-ID`).
  The spec's edit-result payload (8.3.10) is a copy-paste of the deny one, so handle unknown shapes defensively
  and archive the first real one.
- `/api/v3/hiu/subscription/notify` → the LINK/DATA alert. **Acknowledge first** (8.3.12:
  `acknowledgement.eventId` = `event.id`, `response.requestId` = this callback's `REQUEST-ID`), then process
  (3.5). Record every event by `event.id` so a redelivered alert is acknowledged again but never processed twice.

Every callback carries an `x-hiu-id` header naming which of our services it is for. Use it to confirm the
callback belongs to the locker.

### 3.3 Persistence

Extend the existing `subscription_request` table or add tables, via **new additive Alembic migrations only**.
Never drop a table or column that holds rows. The new state needs to hold:
- per patient + locker: `subscriptionRequestId`, `subscriptionId`, status (REQUESTED / GRANTED / DENIED /
  REVOKED / EXPIRED / disabled), categories, period, and timestamps;
- the Setup Locker result (`consentAutoApprovalId`) per patient;
- an alert log keyed by `event.id`: category, hip, care contexts, hiType, received time, and a processing state
  (received → consent requested → consent granted → data requested → data received / failed + reason).

### 3.4 The patient side: routes and UI

Everything goes through the existing app-API router (`X-Aegle-Key` gate) and the testui's single `apiRequest()`
choke point. Use the existing `components/ui/` primitives, no `<fieldset>`. Follow the standing directive that
it must read like a real mobile app. Write the copy in plain patient language.

- **A one-time opt-in** at the patient's first login (or whenever the setup is missing). A clear screen
  explaining that the Aegle Urgent Care locker will collect their records automatically, with Allow / Not now.
  ABDM's PHR-app guidance says the user must be explicitly asked before a subscription is set up, so this must
  never happen silently.
- **Subscriptions screen** (rebuild `SubscriptionsScreen.tsx`):
  - the locker card: name, active / inactive, setup date, auto-approval active or not (from 8.3.16 / 8.3.17);
  - subscription requests, with **Approve** (8.3.4) and **Deny** (8.3.7, reason prompt);
  - active subscriptions, with **details** (8.3.14), **Edit period** (8.3.9: dates only — the spec says HIPs
    and HI types can't be edited), **Pause** (disable) and **Resume** (enable);
  - the combined inbox (8.3.15) where it fits.
  - The patient's lists include **other apps'** subscriptions (e.g. `sbx_001`, "Sanbox Test Hospital"). Show
    them, since they're the patient's own, labelled clearly by `hiu.name` and `requesterType`, so the patient can
    tell the Aegle Urgent Care locker apart from everything else. Patient actions on them (pause / resume) are
    fine. Our automation never touches them.
- Remove the free-text `X-LOCKER-ID` field. The locker ID comes from settings.

### 3.5 The locker automation

- **Ensure on login.** This must be idempotent and must never create duplicates.
  1. Check 8.3.16. If our locker is missing or inactive, show the opt-in; on Allow, call 8.3.18 and store
     **both** IDs it returns (`subscriptionId`, `consentAutoApprovalId`) against the patient. That single call
     is the whole setup. There is no separate subscription request or approval step.
  2. If the locker is present and active, confirm its subscription is still usable: 8.3.17's `subscriptions[]`,
     or 8.3.14 with the stored `subscriptionId`. Treat it as missing if it isn't there, or if it is revoked,
     expired, or past its period end. **Only count subscriptions whose `hiu.id` is our locker ID.** A patient
     can hold subscriptions for other apps (e.g. `sbx_001`), and those must never satisfy this check or be
     acted on.
  3. **Recovery when the locker is active but its subscription isn't.** Whether calling Setup Locker again on an
     already-active locker is allowed (or creates a duplicate) is unknown. Test it **once**, deliberately, on
     the test patient during the live tests, and pick the recovery path from the result: re-run Setup Locker, or
     fall back to 8.3.2 init as the locker (`hiu.id` = `IN2410002590`, categories `LINK` + `DATA`, no `hips`,
     a far-future period end) → `on-init` → approval. Purpose: mirror what Setup Locker itself created
     (`PATRQT`). The spec and Postman examples use `CAREMGT`; only try that if `PATRQT` is rejected, and record
     which worked. Spec §8.1 says a locker's
     subscription is auto-approved; if it isn't, the request shows in the patient's Subscriptions screen.
  4. **Patients set up before this chunk** (`poojaanchaliya@sbx`, set up by hand in Postman): pick their IDs up
     from 8.3.16 / 8.3.17 on their next login, the same way as anyone else. Never hardcode them.
  - Respect a patient's choices: never re-subscribe someone who paused (disabled) or revoked, and never re-add a
    locker they removed, without asking them again through the opt-in.
- **Alert → records.**
  - **LINK** (a new visit was linked): the locker raises a consent request **as the locker** for the alert's
    hospital / care contexts, with purpose, HI types and date range matching the auto-approval policy read in
    Step 0 (3). The purpose is expected to be `PATRQT`, matching the locker's own subscription. The consent chain is `repo/`'s existing HIU code (`server/hiu_consent.py` →
    `on-init` / `notify` / `on-fetch`). `repo/` owns those callback paths; `aegle-phr` must not register them.
    If scoping a consent to a specific hospital / care contexts needs parameters
    `initiate_consent_request()` doesn't have today, **you may extend it in `repo/`**. The change must be
    additive (optional parameters, defaults preserve today's behavior), and existing callers must be unchanged.
  - **DATA** (new data on a known visit): first reuse a GRANTED locker-raised consent that covers this care
    context, HI type and date. Raise a new one only if none does.
  - **Then fetch the data** with `repo/`'s existing `hiu_health_information.py`, with `hiu_id` = the locker ID.
    The automatic step from "consent fetched" to "data requested" must fire **only for locker-raised consents**.
    `repo/server/config.py`'s `HEALTH_INFORMATION_TRIGGER_MODE` is a global switch, and flipping it to `"auto"`
    would change the M3 CLI's behavior for every consent. Prefer an additive, locker-scoped trigger (e.g. an
    allowlist of HIU ids for auto-trigger in `server/callbacks/services/health_information_trigger.py`), or
    trigger from `aegle-phr`'s side. Justify your choice in the report.
  - Update the alert log's processing state at every step. Failures are recorded with their reason, never
    swallowed.
- **Initial sync.** Alerts only cover visits linked *after* the subscription exists. When a patient's locker +
  subscription is first established, run **one** locker-raised consent + fetch for the care contexts already
  linked to them (from the existing "Get All Linked Records" call). This is the new logic applied to existing
  records, not a workaround. Without it a patient's existing records never appear. Record it in the alert log
  (or its own log) the same way, so it runs once per patient.
- **The records view.** `HomeScreen.tsx` keeps its Level 1–3 drill-down and its FHIR reader, but the content it
  shows now comes **only** from data the locker fetched for this patient. A manual "Refresh" on a record re-runs
  the fetch through the locker path (the DATA behavior). There is no other way to pull.

**The security property must hold:** a patient only ever sees data fetched under consents raised by **our own
locker** for **that patient**. `repo/`'s gate (`get_hiu_consent()` only returns consents our own registration
raised and fetched) stays exactly as it is.

---

## 4. The one-time registration tooling

Registration was done by hand in Postman. Add read-only Gateway checks to `repo/tools/m2_test_suite/flows/
bridge_gateway.py` (reuse P18's flows if they exist): list our services with their types, look up one service,
and search Health Lockers by name. Also add the `PUT bridge-service` update as a flow. It must **re-send the
service's existing `isHip` / `isHiu` / `active` values unchanged** — that call replaces the whole record, and a
careless body switches off roles the linking and data-flow work depends on. Reuse `get_gateway_token()` and the
existing GET lookups in `repo/server/auth.py`.

---

## 5. Remove every earlier workaround

**Definition:** any code path that obtains a patient's records, or consent to them, by any route other than
section 1's new logic. That includes code that reads, imports or reuses a consent or identity raised by another
app or registration; endpoint-guessing / "try several variants" code; and anything superseded by the locker.

**Known items (verify each, then remove the code and every caller, route, UI element and test hook):**
- `data_flow.discover_self_view_consents()`, its `/phr/data-flow/discover-self-view-consents` route and its
  `HomeScreen.tsx` caller. It finds consents ABDM granted to *another* app and **writes them into `repo/`'s
  own consent cache** via `save_hiu_consent()`, which defeats the security property above. This is what Aayush
  calls "reading SBX_001 ID and getting all records". `sbx_001` is confirmed as ABDM's own sandbox PHR app
  ("Sanbox Test Hospital"; see its subscription in section 1). **Grep both repos, case-insensitively, for
  `sbx_001` / `SBX_001` / `sbx-001`** and remove every reference. The only place `sbx_001` may still appear
  afterwards is as display data returned by ABDM (e.g. in the patient's own subscription list), never in our
  code.
- `data_flow.request_self_view_consent()` (P9, PATRQT self-view), its route, and `HomeScreen.tsx`'s self-view
  auto-provisioning: `extractCoveringConsents()`, `knownBadConsentIds` (including its localStorage persistence),
  the uncovered-HIP effect, the poll-for-auto-grant logic, `SelfViewWaitingCallout`, and the auto-fetch effect.
- `data_flow.ensure_self_view_auto_approve()` (P12's ordered multi-endpoint live test) and its route.
- `data_flow.ensure_self_subscription()` and `/phr/subscription/ensure-self-subscription` (P13's `CLIENT_ID`-as-hiu
  attempt). This is replaced by 3.5.
- `data_flow.trigger_consent_fetch()` and its route, **if** the normal `repo/` notify → fetch → on-fetch chain
  covers locker consents (verify live). It existed to force a fetch the callback chain wasn't doing.
- **Consent auto-approval duplicates in `aegle_phr/phr/consent.py`.** The patient-facing Consent Manager
  endpoints themselves (spec §6.13–6.15: set up / disable / enable auto-approval) are documented features and
  stay on the Consent screen. But keep **one** implementation of each, matching the PHR Postman collection's
  "FETCH & MANAGE CONSENT REQUESTS" folder (01 auto-approve, 02 disable, 03 enable). Remove the alternate /
  guessed variants (`auto_approve_v3_hiecm` vs `auto_approve` via `/cm/...`, and the `/cm/patients/pin` +
  `verify-pin` path, which exists only in ABDM's old v0.5 reference collection), **and every automatic caller**
  from the records flow. If you can't tell which variant actually works from the code and `abdm_call_log`, stop
  and ask rather than guess.
- `PHR_CLIENT_ID` / `PHR_CLIENT_SECRET` in `repo/server/config.py` + `repo/.env`, **only if** Step 0 (2) confirmed
  the locker lives under `CLIENT_ID`.
- Anything else you find that fits the definition. List it in the report with file:line and the reason.
  **If an item is ambiguous, ask before deleting.**

Removing code never means removing data. Leave existing Postgres rows, `.jsonl` files, `logs/` and `storage/`
untouched. If a table becomes unused, leave it and flag it.

---

## 6. Verification

**Offline:**
- Every Appendix A call builds exactly the documented method, path, headers and body, including the absence of
  `X-AUTH-TOKEN` on locker-side calls.
- The callbacks: dedupe by `event.id`; branch on `notification.status`; acknowledgements echo the right IDs.
- The grep for every item in section 5 comes back empty.
- Login, profile, linked records and the Consent screen still work.
- Delete any scratch test scripts when done.

**Live — ask Aayush before each, and report the exact request and the response (redacted):**
1. Read-only: bridge-services, health-lockers search, 8.3.16 + 8.3.17 + 8.3.14 for `poojaanchaliya@sbx`
   (Step 0).
2. The opt-in → Setup Locker path end to end, on a **second test patient** who doesn't have the locker yet.
   Confirm it returns both IDs, the subscription shows GRANTED with `PATRQT` / all hospitals / LINK + DATA, and
   the app stores both. Note any callbacks that arrive.
3. The recovery question, once, on a test patient: call Setup Locker again for a patient who already has an
   active locker. Does ABDM reject it, return the existing IDs, or create a duplicate? That result decides
   3.5's recovery path.
3a. The HIU-initiated route (8.3.2 init → `on-init` → 8.3.4 approve → 8.3.5 → 8.3.6), on a test patient
   **without** the locker, so a pending request exists to approve. **Never** raise 8.3.2 for Pooja: she already
   has a granted locker subscription.
4. 8.3.13, 8.3.14, 8.3.1, 8.3.15.
5. LINK alert: link a new care context for that patient via the M2 CLI's HIP-Initiated Linking flow → 8.3.11 →
   8.3.12 → locker consent → auto-approved? → fetch → data shown on Home. **Do this twice:**
   - First at a HIP **other than** `IN2410002590`: the clean case.
   - Then at `IN2410002590` itself. There the locker fetches from its own HIP role, so this server both
     pushes and receives the data. That is the self-referential path that once deadlocked the event loop
     (commit `6a1d748`, "Fix event-loop deadlock in M2/M3 self-referential data push"). Confirm it still
     completes, and that the locker's HIU-side state and the HIP-side state stay in their separate stores.
6. DATA alert, if one can be produced (notify care context update for an existing link).
7. Initial sync for the patient.
8. Edit period → 8.3.10 (log the real payload); Pause → Resume.
9. Deny: **only** on a disposable second request. Never deny the patient's real subscription.
10. Regression: HIP-Initiated Linking, the M3 CLI's consent + data flow (confirm the trigger change didn't alter
    it), the Consent screen.

---

## 7. Standing rules (unchanged)

- **No git commit or push.** Leave everything as uncommitted working-tree changes.
- **Never delete or truncate anything under `logs/` or `storage/`**, in either repo.
- **Never print secrets or tokens** in logs, the Console panel or your report: the gateway token, patient
  `X-AUTH-TOKEN`, client secrets. The gateway call uses `Authorization: Bearer <gateway token>`.
- **No throwaway scripts left behind** once they've served their purpose.
- **Testing must not leave real local output changed.** Back up anything a test would overwrite, and restore it
  afterwards.
- **Scope discipline.** Change only what this prompt covers. Flag anything else you notice rather than fixing
  it. Regressions you cause yourself are in scope to fix.
- **`repo/` changes** are limited to the explicit permissions above: the additive `initiate_consent_request()`
  parameters, the locker-scoped data trigger, the `bridge_gateway.py` flows, and the `PHR_CLIENT_ID` removal.
- **When spec and Postman conflict** and Appendix A marks it unresolved, build it so the live call decides.
  Don't pick one by guessing.
- If you add a new runnable tool or CLI flow, include exact run instructions in your report.

## 8. Report back

1. A detailed per-file change report: what changed, where, and why.
2. The workaround-removal inventory: each item, file:line, removed / kept + reason.
3. The Step 0 findings: the locker ID, the owning client and the auto-approval policy, verbatim (redacted).
4. For each live step: the request, the response, and what it **confirmed** versus what it **corrected**.
5. A short summary to paste back into Cowork.

---

## Appendix A — every call, reconciled (spec §8 × PHR Postman collection, 22 Sep 2026)

Host: `https://dev.abdm.gov.in`. **Locker side** = gateway token only
(`Authorization: Bearer`, `REQUEST-ID`, `TIMESTAMP`, `X-CM-ID: sbx`). **Patient side** = the same plus
`X-AUTH-TOKEN: <patient login token>`. Postman has **no saved example responses** for any of these, so the
response shapes below come from the spec's examples and ABDM's older reference collection. Save real ones.

### Gateway prerequisites (§4) — locker side
| Call | Method + path | Notes |
|---|---|---|
| Register / update service | `PUT /api/hiecm/gateway/v3/bridge-service` | Body: `bridgeId, serviceId, name, isHip, isHiu, isHealthLocker, isPhr, endpoints, attributes, active`. Replaces the whole record. |
| List our services | `GET /api/hiecm/gateway/v3/bridge-services` | Shows each service's types. |
| One service | `GET /api/hiecm/gateway/v3/bridge-service/serviceId/{serviceId}` | |
| Search lockers | `GET /api/hiecm/gateway/v3/health-lockers?name=…` | Source of the locker ID. |

### Locker-side calls
**8.3.2 Init** — `POST /api/hiecm/subscription-requests/v3/init` → 202, empty body.
```json
{ "subscription": {
    "purpose": { "text": "Care Management", "code": "CAREMGT", "refUri": "www.abdm.gov.in" },
    "patient": { "id": "<abha address>" },
    "hiu":     { "id": "<locker id>" },
    "categories": ["LINK", "DATA"],
    "period": { "from": "<ISO>", "to": "<ISO>" } } }
```
`hips` is optional; omit it for all hospitals (Postman has it commented out). **Conflict:** the spec lists
`X-AUTH-TOKEN` as required; Postman doesn't send it. Try without it first, and let the live result decide.
**Purpose:** the spec and Postman use `CAREMGT`, but the subscription ABDM itself created for this locker via
Setup Locker is `PATRQT`. Use `PATRQT` first; fall back to `CAREMGT` only if it's rejected. This call is the
recovery / HIU route only; Setup Locker creates the locker's subscription directly.

**8.3.6 Acknowledge a decision** — `POST /api/hiecm/subscription-requests/v3/hiu/on-notify` → 202.
`{"acknowledgement":{"status":"OK","subscriptionRequestId":"…"},"response":{"requestId":"<REQUEST-ID of the hiu/notify being acked>"}}`.
Sent after the `hiu/notify` callback (approve / deny / edit), per the §8.2 diagrams. **Not** after `on-init`.

**8.3.12 Acknowledge an alert** — `POST /api/hiecm/subscription-requests/v3/hiu/care-context/on-notify` → 202.
`{"acknowledgement":{"status":"OK","eventId":"<event.id>"},"response":{"requestId":"<REQUEST-ID of the alert>"}}`.

### Callbacks (on our callback URL; each carries an `x-hiu-id` header)
**8.3.3** `/api/v3/hiu/hiecm/subscription-requests/on-init` —
`{"subscriptionRequest":{"id":"…"},"response":{"requestId":"<our init REQUEST-ID>"}}`. No acknowledgement documented.

**8.3.5 / 8.3.8 / 8.3.10** `/api/v3/hiu/subscription-requests/hiu/notify` — one URL; branch on `notification.status`.
- GRANTED: `{"notification":{"subscriptionRequestId","status":"GRANTED","subscription":{"id","patient":{"id"},"hiu":{"id","name","type"},"sources":[{"hip":{},"categories":[…],"period":{…}}]}}}`. An empty `hip: {}` means all hospitals.
- DENIED: `{"notification":{"subscriptionRequestId","reason","status":"DENIED"}}`.
- Edited: **undocumented** (the spec repeats the deny text). Handle defensively and archive the first real one.

**8.3.11** `/api/v3/hiu/subscription/notify` — the alert:
```json
{ "event": { "id": "…", "published": "…", "subscriptionId": "…", "category": "LINK",
    "content": { "patient": { "id": "…" }, "hip": { "id": "…" },
      "contexts": [ { "careContexts": [ { "patientReference": "…", "careContextReference": "…" } ],
                      "hiType": "Prescription" } ] } } }
```
**Conflict:** the spec's field table says `SubscriptionRequestId`, but its example body and ABDM's real captured
payload carry `subscriptionId`. Follow the example; confirm live.

### Patient-side calls
| # | Method + path | Send | Get back / notes |
|---|---|---|---|
| 8.3.18 | `POST /api/hiecm/subscription-requests/v3/setup-locker` | header `X-LOCKER-ID`; no body | **Live (22 Sep):** `{subscriptionId, consentAutoApprovalId}`. The spec shows only the second. Creates the locker's granted subscription (`PATRQT`, all hospitals, LINK + DATA, 100-year period) **and** its auto-approval policy in one call. |
| 8.3.16 | `GET …/v3/patients/lockers?includeInactive=true` | — | `[{lockerId, lockerName, patientId, isActive, dateCreated, dateModified}]`. The spec lists `includeInactive` as a body param; it's a query param. |
| 8.3.17 | `GET …/v3/patients/lockers/{lockerId}` | — | the locker + `subscriptions[]` + `autoApprovals[]` (each with a full `policy`) |
| 8.3.1 | `GET …/v3/requests?status=ALL&limit=10&offset=0` | — | `requests[]`: `requestId, subscriptionId (null until granted), requestType: HEALTH_LOCKER, status, details`. The spec wrongly lists the params as headers and says "202". |
| 8.3.15 | `GET …/v3/patients/requests?consentLimit=&consentOffset=&subscriptionLimit=&subscriptionOffset=&status=ALL` | — | `{consents:{size,limit,offset,requests[]}, subscriptions:{…}}`. **Live subscription item:** `subscriptionId, requestId, createdAt, lastUpdated, purpose, patient{id}, hiu{id,name,type}, hips[], categories[], period{from,to}, status, requesterType` (`HEALTH_LOCKER` for ours, `HIU` for others). An empty list comes back as `requests: [{}]`; skip items with no ID. It includes **other apps'** subscriptions (e.g. `sbx_001`). `status`: ALL / REQUESTED / DENIED / GRANTED / REVOKED / EXPIRED |
| 8.3.13 | `GET …/v3/request/{subscriptionRequestId}` | — | `status, subscriptionId, requesterType, details…`. The spec's path is missing a hyphen. |
| 8.3.14 | `GET …/v3/{subscriptionId}` | — | `requester, dateGranted, includedSources[]`. The spec's printed URL is a copy of 8.3.13's. |
| 8.3.4 | `POST …/v3/{subscriptionRequestId}/approve` | `{"isApplicableForAllHIPs":true,"includedSources":[{"hiTypes":[8 types],"purpose":{…CAREMGT},"categories":["LINK","DATA"],"period":{…}}],"excludedSources":[]}` | `{subscriptionId, message}`. The spec's `isApplicableForAllHIPs` description says "false" both ways (a typo); `true` = all hospitals. |
| 8.3.7 | `POST …/v3/{subscriptionRequestId}/deny` | `{"reason":"…"}` | `{message}`. The spec's path is missing a hyphen and names the ID `subscription_id`. It is the request ID. |
| 8.3.9 | `PUT …/v3/patients/{subscriptionId}` | `{"hiuId":"<locker id>","subscriptionEditAndApprovalRequest":{"isApplicableForAllHIPs":true,"includedSources":[…],"excludedSources":[]}}` | `{subscriptionId, message}`. Only the period is editable (the spec: "HIP/HI type can't be edited"). |
| — | `POST …/v3/disable/{subscriptionId}` / `POST …/v3/enable/{subscriptionId}` | no body (Postman sends `{}`) | **Postman only**; not in the spec |

`…` = `/api/hiecm/subscription-requests`. The eight HI types: `Prescription, DiagnosticReport, OPConsultation,
DischargeSummary, ImmunizationRecord, HealthDocumentRecord, WellnessRecord, Invoice`.

**IDs, so they don't get mixed up:** `subscriptionRequestId` (from `on-init`) → approve / deny / 8.3.13 / 8.3.6.
`subscriptionId` (from the approve response or GRANTED `hiu/notify`) → edit / disable / enable / 8.3.14, and it's
in every alert. `event.id` → 8.3.12. Every acknowledgement's `response.requestId` = the `REQUEST-ID` of the
callback being acknowledged.
