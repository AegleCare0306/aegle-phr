# CC Prompt — Self-view consent separation + auto-provisioned "just works" access (spec §6/§7)

**Model recommendation: Sonnet, extended thinking ON.** This is a correctness/security fix to an
authorization boundary PLUS a real UX automation layer built on top of it — read the whole rationale
before touching code, including the "working assumption, not yet proven" section below. Don't shortcut
the verification section at the end; it's written around two specific live tests Aayush is running
himself, and this prompt's whole design needs to survive whatever those tests actually show.

**Run this AFTER `CC_PROMPT_P8_consent_manager_pending.md`** — it depends on that chunk's Approve
picker existing, both for the fallback path (see below) and for any doctor/third-party request.

## The original bug, stated plainly (still the reason this exists)

PHR (the patient's own app), HIP (a facility), and HIU (an entity requesting a patient's data) are
three genuinely distinct roles in ABDM's model. This sandbox happens to operate all three under one
ABDM client (`SBXID_046112`) — a legitimate sandbox simplification, but it must never mean the CODE
treats them as interchangeable. Today it does, in exactly one place: `HomeScreen.tsx`'s
`extractCoveringConsents()` picks **whichever consent artefact happens to be `GRANTED` for a given
HIP**, regardless of who requested it or why — meaning a doctor's own consent and the patient's own
self-view could resolve to the exact same artefact. Revoking a doctor's access could silently break
the patient's own "Pull Records" for that facility, or vice versa. Confirmed this is the ONLY place in
the codebase this pattern exists (`consent.py`, `links.py`, `providers.py`, `profile_link.py`,
`abha_card.py`, every other `testui/src/routes/*.tsx` all take explicit IDs from the caller, never
infer/borrow across roles) — don't go looking for a second instance, there isn't one, but flag anything
else that smells like "grab whichever X is convenient" rather than silently fixing it.

**The fix for THIS part is simple and settled, don't overthink it**: filter strictly on
`consentDetail.purpose.code === "PATRQT"` (the spec's own real "Self-Requested" purpose code — confirmed
in the spec's valid-purpose-code list alongside `CAREMGT`/`BTG`/`PUBHLTH`/`HPAYMT`/`DSRCH`). **No
additional `requester.name` check is needed** — a separate investigation this same day confirmed
`aegle_phr`'s own Fetch Records path can NEVER succeed using a consent raised through a different ABDM
registration in the first place: `repo/server/hiu_health_information.py`'s own precondition check
(`get_hiu_consent(consent_id)`) only ever has a row for a consent OUR OWN registration itself raised and
fetched — a consent from ABDM's own external sandbox app, or any other company's app, simply isn't in
that local cache and the call fails locally with a clear error before ever reaching ABDM. So
`purpose.code === "PATRQT"` alone is sufficient: it's the only filter needed to stop self-view from ever
blending with a doctor's/third-party's grant, and there's no remaining scenario where "which specific
app raised this PATRQT consent" needs to be separately checked on top of it.

## THE WORKING ASSUMPTION THIS PROMPT IS BUILT AROUND — NOT YET PROVEN, READ THIS CAREFULLY

Aayush has directly observed, from real use of ABDM's own external sandbox/reference app, that he has
**never once manually approved a self-view consent request** — records just become viewable after
linking, with no visible "go approve this" step. This matches the live evidence captured earlier the
same day: an externally-raised `PATRQT` consent notify arrived at our HIP endpoint already
`"status": "GRANTED"`, about one second after the corresponding UIL confirm — no observable pending
window at all.

**The working theory**: Consent Manager's whole "request sits as `REQUESTED` until the patient
approves" mechanism exists because a THIRD PARTY is asking for access. `PATRQT` ("Self Requested") is
structurally different — the requester and the person being asked are the same entity (the patient,
acting through their own already-authenticated app session). ABDM may auto-grant `PATRQT` requests
specifically because there's no actual third party whose permission is needed.

**This has NOT been confirmed for THIS project's own registration raising a PATRQT request** — every
piece of evidence so far comes from ABDM's own external sandbox app, not from anything raised through
`repo/`'s own `initiate_consent_request()`. Aayush is going to test this directly (see Verification).
**Build this prompt's auto-provisioning behavior around the assumption that it auto-grants, but ALWAYS
with a working fallback to manual approval if it turns out not to** — do not build anything that breaks
or gets stuck if the assumption is wrong. Concretely: poll for the request to reach `GRANTED` for a
bounded window after raising it; if it does, proceed automatically (see below); if it doesn't, the
request simply sits in the Requests tab exactly like any other pending request, approvable through
P8's existing picker — no special-casing needed there, a `PATRQT` request is just a request. Nothing
about this design requires the assumption to be true to keep working; it just gets less automatic if
it's false.

## What to build

### 1. Raise a dedicated self-view consent request (backend)

Add to `aegle_phr/phr/data_flow.py` (same lazy-import-from-`repo/`, `ImportError`-guarded pattern as
its two existing functions — the same one-time, confirmed exception: import and call `repo/`'s code,
never modify a file under `repo/`):

- `request_self_view_consent(hi_types, date_range_from, date_range_to, patient_abha_address)` — calls
  `repo/server/hiu_consent.py`'s existing `initiate_consent_request()` with:
  - `purpose_code="PATRQT"`, `purpose_text="Self Requested"`, `purpose_ref_uri="www.abdm.gov.in"`.
  - `requester_name="Aegle PHR — My Records"` (or similar) — purely a display label now (so the
    Requests tab reads clearly if a human ever needs to look at or approve it), NOT a security
    boundary — see the settled reasoning above for why no code needs to match against this value.
  - `requester_identifier_type`/`value`/`system` — reuse whatever placeholder values
    `hiu_consent.py`'s own CLI reference already uses; not load-bearing.
  - `hiu_id` — our one shared registration's HIU identity, same as every other HIU-role call in this
    project.
  - `hip=None`, `careContexts=None` on the request itself, per `initiate_consent_request()`'s own
    documented behavior — the patient (or, per the working assumption, ABDM automatically) resolves
    which HIP(s) this covers.
  - **Deliberately broad, not per-HIP**: this is ONE request per call, not one per linked facility —
    `hip`/`careContexts` being `None` on the request means HIP selection happens at approval time (via
    P8's own multi-select picker, which already supports naming several HIPs in one `consents[]`
    submission) or, per the working assumption, gets resolved automatically by ABDM. Don't raise N
    separate requests for N linked HIPs.
- No new callback wiring needed — `repo/`'s existing on-init/notify/on-fetch callback chain already
  handles this automatically; confirmed by reading all three service files.
- Add one new route for this (`POST`, alongside Data Flow's other two routes).

### 2. Auto-provision on login/Home load — raise once, poll for grant, don't nag

On Home screen load (after Linked Records is fetched), determine whether any linked HIP lacks a
`PATRQT`-purposed artefact that's GRANTED **or** already sitting as a pending request. If any linked HIP
is uncovered:

- Raise ONE `request_self_view_consent()` call (broad `hiTypes` covering what's actually linked, a
  date range wide enough to be practically useful — mirror whatever convention other consent-raising
  code in this project already uses for a sensible default range, don't invent a new one).
- **Dedup across logins**: before raising, check whether a `PATRQT` request from this app is already
  `REQUESTED` or `GRANTED` (via the same consent-requests listing Consent Manager already fetches) —
  if one exists, don't raise a second one. Every login should NOT spam a new duplicate request; only a
  genuinely newly-linked, not-yet-covered HIP should ever trigger a fresh one.
- After raising, poll (short, bounded — same "a few attempts, clear timeout, not an infinite loop"
  convention as Data Flow's own polling) for the request to reach `GRANTED`.
  - **If it grants within the window**: proceed straight to step 3 (auto-fetch) for the newly-covered
    HIP(s) — no approval UI shown to the patient at all for this.
  - **If it doesn't**: stop polling, leave it alone. It's now a normal pending request, visible in the
    Requests tab, approvable via P8's picker like anything else. Don't show an error — this isn't a
    failure state, it's "waiting on the patient," exactly like a doctor's request would be.
- This check should re-run on every Home load (cheap — comparing linked HIPs against
  already-covered/already-pending ones), not just once at login, so a NEWLY linked record later in the
  same session also gets picked up without the patient having to do anything.

### 3. Auto-fetch — no manual "Fetch Record" click needed once a HIP is covered

For every HIP with a GRANTED `PATRQT` artefact (whether it auto-granted per step 2, or was manually
approved as the fallback), Home should automatically call `request_health_information()` +
`get_health_information_status()` and render the result — the patient should not need to click
anything to see their own linked records' actual content once access exists. Concretely:

- Trigger this automatically per covered HIP on Home load (or when a HIP newly becomes covered via
  step 2's auto-grant), not on a button click.
- Still show a clear, per-HIP loading/status state while this is in flight (this is genuinely async
  and can take a few seconds) — don't make it look instant or hide that a real round trip is happening.
- Keep a manual "Refresh" action per record too, for the patient to force a fresh pull on demand (e.g.
  after a new visit) — auto-fetch-on-load doesn't replace the ability to explicitly re-pull.
- A HIP that's linked but NOT yet covered (still mid-auto-provisioning, or waiting on manual approval
  per step 2's fallback) should show its own clear state ("waiting for access" / "pending approval"),
  not an error and not a blank Fetch Record button pretending nothing is happening.

### 4. Rewrite `extractCoveringConsents()` — the settled, simple filter

Filter strictly on `consentDetail.purpose.code === "PATRQT"` — remove the old "any GRANTED artefact"
branch completely, don't leave it as a fallback. No `requester.name` check needed (see the settled
reasoning above — cross-registration reuse is already structurally impossible via `repo/`'s own local
cache precondition, so this filter only ever needs to keep self-view from blending with a
doctor's/third-party's `CAREMGT`-or-other-purpose grant, which `purpose.code` alone fully guarantees).

### 5. Update every banner/docstring that described the old behavior

`data_flow.py`'s and `HomeScreen.tsx`'s own banners currently describe "first GRANTED match per HIP" as
a flagged simplification — rewrite to describe the actual fix (self-view is its own `PATRQT`-purposed
consent, filtered on purpose code alone, auto-provisioned per steps 2-3), and explicitly document the
working assumption from above (auto-grant, not yet proven for our own registration, with its fallback)
so it isn't silently re-assumed as fact later if it turns out false.

## What's explicitly NOT in scope here

- Not fixing/touching anything in Consent Manager's own three gaps beyond what's needed for the
  fallback path — that's `CC_PROMPT_P8`, run first.
- Not building a second real ABDM client/HIU registration.
- Not making `permission.frequency` caller-configurable in `initiate_consent_request()` — it's
  currently hardcoded (`{"unit": "HOUR", "value": 0, "repeats": 0}`) inside `repo/`'s own function and
  this pass doesn't touch `repo/`. If Aayush's live testing shows repeat fetches against the same
  granted consent get rejected after some number of pulls, that's a separate follow-up, not something
  to silently work around here (e.g. don't build a "cache the last pull forever" workaround without
  being asked — just report exactly what was observed).
- Existing artefacts using `CAREMGT` will NOT match the new filter — correct, not a regression.
- Don't touch `repo/`. No git commit/push/init. Never print secrets/tokens into your report.

## Verification — built around Aayush's own two planned live tests, report exactly what happens

Run `npm run typecheck && npm run build` as you go, same as every prior chunk. Beyond that, this
chunk's real verification is two live tests Aayush is running himself once the build is ready — report
precisely what you observe for each, including if either contradicts the working assumption above (that
is a valid, useful outcome, not a failure to fix quietly):

1. **HIP-initiated linking, then log into aegle-phr, with zero manual approval action.** Link a record
   via HIP-initiated linking, then open aegle-phr fresh. Expected per the working assumption: the
   auto-provisioning in step 2 raises a self-view request, it auto-grants within the poll window with
   no approval screen ever shown, and step 3 auto-fetches so the record's real content is visible with
   no click at all. If instead the request sits as `REQUESTED` and needs manual approval via the
   Requests tab — that's the assumption being wrong, not a bug in this build; report it plainly, the
   fallback path (P8's picker) should still make it work with one extra manual step.
2. **Link a different record via UIL in ABDM's own external sandbox app, then try to view it in
   aegle-phr.** Expected: aegle-phr should NOT be able to silently use the sandbox app's own self-view
   grant — it's a different registration. aegle-phr should instead recognize this HIP as
   linked-but-uncovered and go through its OWN auto-provisioning (step 2) to get its OWN access, same
   as any other newly-linked, not-yet-covered HIP. This is the direct test that the structural
   registration-boundary reasoning (not a `requester.name` check) is what's actually protecting
   cross-app reuse — confirm aegle-phr raises its own request rather than either failing outright or
   somehow using the sandbox app's grant.

Report both outcomes exactly as observed, including timing (how long auto-grant/auto-fetch actually
took) and anything that didn't match the expected shape above — this prompt's own working assumption is
explicitly allowed to be wrong, and finding out which parts are wrong is the point of these two tests.
