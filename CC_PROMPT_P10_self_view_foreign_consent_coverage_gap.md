# P10 — Self-view auto-provisioning: a foreign PATRQT consent is wrongly treated as "coverage"

## Recommended model
Sonnet, extended thinking **ON**. This touches the same authorization-boundary logic P9 just built
(self-view consent selection/auto-provisioning) — per this project's own standing policy, extended
thinking stays on for any chunk touching an authorization boundary or cross-repo integration.

## Context you need (read `HomeScreen.tsx`'s own banner above `extractCoveringConsents()` and the P9
self-view effect first — both already document most of this correctly; this prompt is about one gap
in the auto-provisioning logic they don't yet cover)

P9 (`CC_PROMPT_P9_self_view_consent_separation.md`) shipped and is largely working exactly as
designed: `extractCoveringConsents()` filters Consent Manager artefacts to `purpose.code === "PATRQT"`,
and `repo/server/hiu_health_information.py`'s own local-cache precondition means a consent raised by a
DIFFERENT app/registration (e.g. ABDM's own external sandbox app self-granting itself PATRQT access)
fails cleanly with a clear "no local record of consent" error instead of silently succeeding. That part
is proven correct with a real live test today (2026-09-02) — the security boundary holds.

**What's NOT yet working**: a live test just surfaced a real gap in the auto-provisioning logic itself,
not the fetch-safety logic.

## The confirmed bug, step by step (verified today against real storage files, logs, and the current code)

1. Aayush ran HIP-Initiated Linking for patient Pooja Rameshkumar (`poojaanchaliya@sbx` /
   `91466530750069@sbx`) at "Aayush Health Care" (`hip_id: IN3310002215`).
2. ABDM's own external sandbox app auto-granted itself a PATRQT self-view consent for that exact HIP,
   same as every other link event we've observed (confirmed in `repo/storage/consents.jsonl`, consent
   id `6e781b4f-f220-4c3f-9678-11cace94029f`, the familiar ~100-year `date_range` signature).
3. `aegle-phr`'s "get all consent artefacts" call (Consent Manager, §6) returns this consent along with
   everything else tied to the patient's ABHA — Consent Manager doesn't scope its response to consents
   WE raised. `extractCoveringConsents()` correctly matches it (`purpose.code === "PATRQT"`, `GRANTED`)
   and adds it to the `covering` Map for `hipId: IN3310002215`.
4. **The bug**: `HomeScreen.tsx`'s P9 self-view effect (~line 819-905) decides whether to raise our own
   self-view request like this:
   ```
   const anyUncoveredHip = groupByHip(records).some((group) => !covering.has(group.key));
   if (!anyUncoveredHip) { ...; return; }   // exits WITHOUT ever calling getAllConsentRequests
   ```
   Since `covering.has("IN3310002215")` is already true — because of the FOREIGN consent from step 3,
   not anything of ours — this HIP reads as "already covered." The effect returns immediately. It never
   calls `getAllConsentRequests`, never raises our own PATRQT request, full stop.
5. Confirmed via direct evidence this really did happen, not just in theory: `repo/storage/
   pending_consent_requests.jsonl` and `pending_consent_requests_by_consent_request_id.jsonl` have had
   NO new entries since 08:06 UTC (13:36 IST) — well before Pooja's 17:06 IST login/linking test today.
   `repo/logs/server_2026-09-02.log` around that login shows only profile/links/artefact-list fetches,
   no `POST .../consent/v3/request/init` call anywhere. Our own self-view request genuinely never fired.
6. Separately, the P9 item-3 auto-fetch effect (~line 986-994) sees this same HIP in `coveringConsents`
   and immediately calls `pullRecords(hipKey)`. That correctly, cleanly fails — `requestHealthInformation()`
   returns `{ok: false, error: "No local record of consent '6e781b4f-...' in repo/'s own consent cache...
   aegle-phr's own live Consent Manager reads straight from ABDM and never populates repo/'s local cache,
   so a consent showing GRANTED there may still be unusable here."}` (this exact string comes from
   `aegle_phr/phr/data_flow.py` around line 333) — and that raw result is what surfaces in the UI. This
   part of the code is doing exactly what it was written to do; it's just never given a chance to try a
   consent that would actually work, because step 4 never tried to get one.

Net effect: Pooja can see the linked record in both apps (linking never needed consent), can view the
actual content in ABDM's own sandbox app (its own self-granted consent works fine there, in ITS
registration), but gets a clean failure in `aegle-phr` — not because anything is broken, but because
our own auto-provisioning never got triggered at all.

## The fix — two parts, both needed

**Part 1 — "covered" must mean "actually fetchable by us," not "some PATRQT-GRANTED artefact exists."**
The self-view effect's coverage check (`anyUncoveredHip`, and by extension whatever the auto-fetch
effect trusts as "covering") needs to stop trusting Consent Manager's artefact list at face value. The
only way to know for certain whether a specific `consentId` is usable is either (a) to have already
successfully pulled from it, or (b) to have raised it ourselves via `request_self_view_consent()` in
this same session/flow. Recommended approach: track a small piece of state — a `Set<string>` (or
similar) of consent IDs confirmed NOT locally fetchable, populated the moment `pullRecords()` gets back
this specific "no local record of consent" failure. Feed that into both:
  - The self-view effect's coverage check — a HIP whose only "covering" consent is in this known-bad
    set should count as uncovered, so the effect actually runs and raises our own request.
  - `extractCoveringConsents()`'s consumers (or the pull path itself) — should not keep retrying the
    same known-bad consent id for that HIP once it's confirmed broken.

**Part 2 — once our own request is raised and (eventually) granted, the SAME HIP can end up with TWO
GRANTED PATRQT artefacts** (the foreign one, still sitting there, and our own new one). Consent Manager
doesn't guarantee ordering, so `extractCoveringConsents()`'s current "first GRANTED PATRQT match per HIP
wins, `map.has(hipId)` skips the rest" logic could keep landing on the foreign, still-broken one forever,
even after our own good one exists — meaning the bug could resurface indefinitely rather than resolving
once granted. Fix this by making consent SELECTION for a HIP robust to multiple candidates: either (a)
have `extractCoveringConsents()` prefer a consent id NOT in the known-bad set when more than one GRANTED
PATRQT artefact exists for the same HIP, or (b) have the pull path itself try the next available
candidate for that HIP on a "no local record" failure instead of giving up. Either is acceptable — pick
whichever fits the existing code shape better; the requirement is just that a working consent, once it
exists, actually gets used instead of a known-broken one sitting first in ABDM's response ordering.

**Recommended, not required**: have `data_flow.py`'s error response include a small, stable,
machine-checkable signal alongside the human-readable message (e.g. a `reason` or `code` field like
`"consent_not_in_local_cache"`), rather than the frontend needing to string-match the prose error
message to detect this specific case. String-matching a human-readable message is fragile against future
wording changes; a caller checking `response.error === "..."` against prose is exactly the kind of thing
that silently breaks later. Keep the existing message too (`SendUserFile`/CLI-facing readability still
matters) — just add a short field next to it that's meant to be checked programmatically.

## What's explicitly NOT in scope
- No change to `extractCoveringConsents()`'s core PATRQT/GRANTED filter — that part is correct and
  proven; this prompt is only about what happens once more than one candidate exists per HIP.
- No change to `repo/` — this is entirely `aegle-phr`'s own frontend (plus a small, optional backend
  response-shape addition in `aegle_phr/phr/data_flow.py`, NOT `repo/`).
- Don't add retry/backoff tuning beyond what's needed to stop repeatedly hammering a known-bad consent
  id — the existing poll budgets (`SELF_VIEW_POLL_MAX_ATTEMPTS`, `POLL_MAX_ATTEMPTS`) are fine as-is.

## Verification (Aayush will run this live against the real ABDM sandbox — report the actual observed
outcome, not an assumption; either "it worked" or "here's exactly what happened instead" is useful)
Using Pooja's account and the "Aayush Health Care" HIP already linked today (which already has ABDM's
own foreign PATRQT consent sitting there from the sandbox app):
1. Refresh/re-login in `aegle-phr`. Confirm — via the server log, same as today's diagnosis — that a
   real `POST .../consent/v3/request/init` call now fires for this account, even though a foreign
   PATRQT-GRANTED artefact already exists for that HIP. This is the key regression check for Part 1.
2. Whether that request auto-grants (the P9 working assumption) or falls back to `pending_approval`
   (P8's manual Approve picker), confirm records eventually become viewable in `aegle-phr` for that HIP
   — not the raw "no local record of consent" failure Aayush saw today.
3. If it does auto-grant, confirm the fetch actually uses OUR OWN newly-granted consent (not the
   foreign one still sitting there) — this is the Part 2 check. `repo/storage/hiu_consents.jsonl` should
   gain a new entry for whatever consent id ends up used.
4. Confirm no infinite loop — the UI shouldn't keep re-raising requests or re-attempting the same known-
   bad consent id repeatedly once it's confirmed unusable.
5. **This fix is NOT specific to HIP-Initiated Linking** — `groupByHip()`/`extractLinkedRecords()` key
   purely off `hipId` from "Get All Link Records" (§6.12/§9.3.5), which carries no field distinguishing
   how a HIP got linked (UIL via any app, or HIP-Initiated). So the exact same bug, and the exact same
   fix, applies to a record UIL-linked through a completely different app (e.g. ABDM's own sandbox app).
   Aayush explicitly wants this case covered too — repeat steps 1-4 above for a HIP that was UIL-linked
   through the sandbox app rather than HIP-Initiated-linked, and confirm `aegle-phr` ends up with real,
   working access to it (own consent, own fetch) the same way. If this case behaves differently from the
   HIP-Initiated one for any reason, that's a real finding to report, not an assumption to wave through.
