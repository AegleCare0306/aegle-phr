# CC Prompt — Consent Manager: everything still pending (spec §6)

**Model recommendation: Sonnet, extended thinking ON.** The Approve picker is the most structurally
involved frontend piece built for this project so far (cross-references Linked Records data from a
DIFFERENT screen, builds a multi-entry request body by hand) and the artefact-shape item asks you to
actually resolve a live ambiguity, not just implement a documented contract — worth the extra care,
same reasoning as the Data Flow chunk.

## Where this project actually stands on Consent Manager right now — read this before touching code

All 11 of spec §6's endpoints (plus Approve, which is Postman-only — see `consent.py`'s own banner)
already exist as backend functions in `aegle_phr/phr/consent.py`. **"Pending API work" here is NOT
about missing endpoints** — it's three specific, already-flagged gaps in `ConsentScreen.tsx`'s own
banner (read it in full before starting, it documents its own history accurately):

1. **Approve is completely unwired.** The button/flow doesn't exist — Level 2 of a still-open
   (`REQUESTED`) request only offers Deny today. The backend function (`approve_consent_request()`)
   is ready and waiting.
2. **The artefact shape (#9/#11) is an unresolved live ambiguity, not just an unconfirmed contract** —
   and it's the leading hypothesis for a real bug Aayush already hit (2026-09-01: not being able to
   revoke a consent at all). This is worth resolving properly, not just leaving defensive.
3. **Auto-approve's enable/disable consentId has no documented source anywhere** — confirmed directly
   against the spec text itself this pass (§6.13's response is `202`, no body, in the PDF; §6.14/6.15
   take `{{consentId}}` in the URL with no documented way to learn it). This one may not be fully
   fixable — see its own section below for what "pending" means here.

Deny (#7) and Revoke (#8) both already work correctly — Revoke's consentId bug from earlier in the
project is already fixed (`consentDetail.consentId`, confirmed against real stored data). Don't touch
either unless something below requires it.

## 1. Build the Approve picker (the main piece of work here)

**Why it's stuck today**: the original plan (documented in `consent.py`'s own docstring) was
"full-acceptance-only" — submit back exactly what the request named, no picker needed. That plan
doesn't work: a live capture of #5 (`GetConsentRequestDetails`, what Level 2 fetches for an open
request) confirmed its shape is REQUEST-shaped (`requestId`/`status`/`purpose`/`patient`/`hiu`/
`requester`/`hiTypes`/`permission`) — it never carries a `hip`/`careContexts` to accept as-is. There is
nothing to submit until the patient actually picks which linked HIP(s) and care context(s) they're
granting access to.

**Source of choices**: `HomeScreen.tsx`'s own Linked Records data (spec §9,
`getAllLinkedRecords()`/equivalent — check its exact current name, it's been touched since this project
last looked at it closely) is the only place this project has HIP + care-context data. Reuse that call
(or its already-fetched result if `HomeScreen.tsx`'s state is reachable / worth lifting one level — your
call on the cleanest way to get the data into `ConsentScreen.tsx` without duplicating fetch logic
wastefully; a second independent fetch of the same endpoint is also acceptable if lifting state is
awkward, this app already re-fetches the same data from multiple screens elsewhere).

**Filtering by the request's own `hiTypes`**: the request itself declares what hiTypes it wants
(visible on #5's response, already rendered in Level 2 today). If a linked record's own care-context
data carries a `hiType`/similar field, filter the picker to matching records; if it does NOT (check —
this project has never confirmed whether Linked Records items carry an hiType field at all), don't
invent a filter that doesn't exist in the data — show all linked HIPs/care-contexts unfiltered and
just LABEL the request's own wanted hiTypes prominently above the picker so the patient can judge for
themselves. Report which case it turned out to be.

**Submitting**: build one entry per selected HIP in `consents[]` — `hip.id`, that HIP's selected
`careContexts` (`patientReference`/`careContextReference`), `hiTypes` = the request's own hiTypes
(don't let the patient narrow hiTypes per-HIP, that's a documented nice-to-have, not this pass),
`permission` = the request's own `permission` object UNCHANGED (dateRange/frequency/accessMode/
dataEraseAt) — this part of the original "full-acceptance" plan was fine, it's only the HIP/
careContexts selection that needed a picker. Call `approve_consent_request(consent_request_id,
consents)` with the built array.

**UI**: multi-select checkboxes grouped by HIP (mirror `HomeScreen.tsx`'s own `groupByHip()` grouping
if reusing its data shape makes that natural), inside whatever `Card`/`CardGrid` primitives the design
pass established — this is a NEW selection UI, not a restyle, but should look consistent with
everything else. An empty Linked Records list (patient has approved nothing to link yet) should render
a clear message ("no linked facilities to grant access from yet") rather than a blank picker or a
confusing empty Approve button.

## 2. Resolve the artefact shape (#9/#11) — don't just leave it defensive, actually find out

`extractArtefactItem()` in `ConsentScreen.tsx` (and the equivalent logic in `HomeScreen.tsx`'s
`extractCoveringConsents()` — same endpoint, same ambiguity, keep them in sync) currently tries a
wrapped shape (`{status, consentDetail: {...}, signature}`) first, falling back to flat. **Actually
settle this against a live call**: fetch #11 (`GetAllConsentArtefacts`) for a real GRANTED consent,
look at the RAW response via `RawBody` (or console/log it directly), and determine definitively which
shape it actually is. Update `consent.py`'s docstring AND both screens' banners with the confirmed
answer instead of "UNCONFIRMED, hypothesized." If the wrapped-shape assumption turns out to be wrong
and flat is correct (or vice versa), fix the primary check accordingly (keep a defensive fallback for
the other shape regardless — same discipline as every other module here — but the ORDER should now
be evidence-based, not a guess). If this was indeed why Revoke looked broken before, confirm that
Revoke and the Approved-tab list both work end-to-end now with real data.

## 3. Auto-approve's consentId gap — flag honestly, improve what little can be improved

Re-confirmed directly against the spec text this pass: §6.13 (create the policy) responds `202`,
literally no body documented anywhere (spec or Postman); §6.14/§6.15 (disable/enable) take
`{{consentId}}` in the URL path with no documented way for a caller to ever learn that value. This may
be a genuine spec gap, not something fixable from this side. Two concrete things worth doing anyway:

- **Actually try it live once and look at the raw response of §6.13**, even though the docs say
  there's nothing there — if ANY body comes back (even undocumented), check specifically for an `id`/
  `consentId`/`policyId`-shaped field and report it. If it's genuinely empty, say so definitively
  (update the docstring from "UNCONFIRMED" to "confirmed empty, live-tested <date>") rather than
  leaving it a permanent open question.
- **Improve the manual-entry field's own copy**, since a bare unlabeled textbox is a bad user
  experience for a real, standing spec gap: explain plainly that ABDM doesn't document how to discover
  this identifier, and that the patient needs the `consentId` of an existing GRANTED consent artefact
  (visible in "Approved" tab / Level 3) to toggle its auto-approve state. If the patient reached this
  screen FROM a Level-3 artefact view (a `consentId` is already in scope there), prefill the field with
  it rather than leaving it blank — a small, real UX improvement even though the underlying spec gap
  itself can't be closed.

## What's explicitly NOT in scope here

- `HomeScreen.tsx`'s `extractCoveringConsents()` "first grant only per HIP" simplification (flagged in
  its own banner) — that's a Data Flow (§7) UX simplification, not a Consent Manager endpoint gap.
  Don't touch it as part of this chunk; just don't let anything here (especially the artefact-shape
  fix) silently break it — re-check it still works if you change the shared parsing logic.
- No changes to Deny or Revoke's own logic — both already correct.
- No narrowing-hiTypes-per-HIP on Approve (documented nice-to-have, not this pass).
- No state/district-style picker infrastructure, no new screens — Approve's picker lives inside
  `ConsentScreen.tsx`'s existing Level 2, same screen structure as today.
- Don't touch `repo/`. No git commit/push/init. Never print secrets/tokens into your report.

## Verification

Approve: run the full loop against a genuinely open (`REQUESTED`) consent request — pick at least one
HIP/care-context via the new picker, submit, confirm the request's status flips to `GRANTED` and a new
artefact appears in the Approved tab / #9 for that request. Artefact shape: confirm with a real #11
call and report the definitive shape found. Auto-approve: report the raw result of an actual live
§6.13 call (body or confirmed-empty) and confirm the prefill behavior works when reached from Level 3.
Run `npm run typecheck && npm run build` before calling this done, same as every prior chunk.
