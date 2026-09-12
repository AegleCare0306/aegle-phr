# P12 (REVISED again, per Aayush's direct instruction) — ordered live test: /api/hiecm/ + facility id, then /api/hiecm/ + CLIENT_ID, then /cm/ + CLIENT_ID

**This replaces the previous version of this file.** We genuinely don't know which of two documented
endpoints (or which HIU identity value) is correct — two official-ish sources disagree, and neither has
a proven live success under our own registration. Rather than guess once, Aayush asked for a specific
ordered sequence of live tests so we get a definitive answer instead of more theory.

## Recommended model
Sonnet, extended thinking **ON** — same reasoning as P11/P12: this sets up (or tests setting up) a
standing pre-authorization policy at ABDM, an authorization-boundary change.

## Why this exact sequence
Two competing endpoints, both "documented" somewhere, neither ever proven under our own registration:
- `{abdm_hiecm_base_url}/consent/v3/auto/approve` (i.e. `.../api/hiecm/consent/v3/auto/approve`) — matches
  this project's own "PHR" Postman collection AND the spec PDF (§6.13), uses the same header convention
  (`Authorization` + `X-AUTH-TOKEN` + `X-CM-ID` + REQUEST-ID/TIMESTAMP) as every other confirmed-working
  call in this project. Never once actually fired successfully by anyone we have evidence of — no saved
  Postman response, nothing in our own logs.
- `{abdm_cm_base_url}/consents/auto-approve` (i.e. `.../cm/consents/auto-approve`, P11's implementation)
  — matches the public ABDM sandbox docs' own "Building a PHR App" walkthrough (section 5.7, written
  specifically for PHR apps, not generic HIUs), and has one real captured success elsewhere (a genuine
  `200`/`autoApprovalId` in Postman's generic "ABDM Collection" example) — but has failed 3 separate
  times against OUR registration with `{"code": "1513", "message": "Invalid HIU ID"}`, using a facility
  id, facility id + name, and an internal numeric id — never yet tried with `CLIENT_ID`.

Rather than pick one, run this exact ordered sequence and report which one actually works:

1. **`/api/hiecm/consent/v3/auto/approve` with a facility id** (`HIPS[0]["hip_id"]`, `"IN3310002215"` —
   the SAME value `request_self_view_consent()` already uses successfully for the separate
   `consent/v3/request/init` call). This is a brand-new combination — nobody has tried this specific
   endpoint at all yet, with any identity value. If this alone works, the fix is: this endpoint was
   right all along, and the facility id was right all along too — P11's whole `/cm/...` detour was
   unnecessary.
2. **`/api/hiecm/consent/v3/auto/approve` with `CLIENT_ID`** (`server/config.py`, `"SBXID_046112"`) —
   only if step 1 fails. Tests whether this endpoint is right but wants the bridge id specifically,
   not a facility id.
3. **`/cm/consents/auto-approve` (P11's existing 3-call sequence) with `CLIENT_ID`** — only if step 2
   fails. Tests whether P11's endpoint was right all along and the failure was purely the facility-id
   value in all three prior attempts.

Stop at the first one that returns a real 2xx. If all three fail, report the exact status/body for each
— that's the point to stop guessing and ask ABDM sandbox support directly, since every plausible
(endpoint × identity) combination we can think of will have been tried.

## What to do
1. In `aegle_phr/phr/consent.py`, add a new function `auto_approve_v3_hiecm(settings, x_auth_token,
   hiu_id, hi_types, purpose_text, purpose_code, purpose_ref_uri, period_from, period_to,
   is_applicable_for_all_hips=True, hiu_name=None) -> AbdmResult` calling
   `POST {abdm_hiecm_base_url}/consent/v3/auto/approve` with the SAME header-building helper every other
   `abdm_hiecm_base_url` call in this file already uses (`Authorization: Bearer {get_gateway_token()}` +
   `X-AUTH-TOKEN: <patient session token>` + `X-CM-ID` + REQUEST-ID/TIMESTAMP) — do not hand-roll a new
   header scheme. Body shape identical to the existing `auto_approve()`'s body builder:
   `{isApplicableForAllHIPs, hiu: {id: hiu_id, name: hiu_name} or {id: hiu_id}, includedSources:
   [{hiTypes, purpose, period}], excludedSources: []}`. Do NOT modify or remove the existing
   `auto_approve()` (the `/cm/...` one) — both functions stay, side by side.
2. In `data_flow.py::ensure_self_view_auto_approve()`, replace the current single-attempt logic with the
   exact 3-step ordered sequence above:
   - Step 1: `auto_approve_v3_hiecm(..., hiu_id=HIPS[0]["hip_id"])`. On 2xx, stop, use it.
   - Step 2 (only if step 1 didn't 2xx): `auto_approve_v3_hiecm(..., hiu_id=CLIENT_ID)` (import
     `CLIENT_ID` from `server.config`, same way `HIPS` is already imported there). On 2xx, stop, use it.
   - Step 3 (only if step 2 didn't 2xx): the existing `auto_approve(..., hiu_id=CLIENT_ID)` (the `/cm/...`
     sequence — remove the `find_bridge_service_by_id()` numeric-id lookup, that theory is superseded;
     just use `CLIENT_ID` directly here too).
   - Remove the old numeric-id-lookup code path entirely (the `find_bridge_service_by_id()` call and its
     surrounding logic) — it's superseded by this ordered sequence.
3. **Log clearly which step succeeded (or that all three failed) and the exact status/error body for
   each attempted step** — this is a diagnostic run as much as a fix, and Aayush needs to know definitively
   which (endpoint × identity) combination is correct, not just whether self-view ends up working.
4. **Do NOT touch `request_self_view_consent()`'s own `hiu_id`** (still `HIPS[0]["hip_id"]`) — unrelated,
   already proven correct, out of scope here.

## Verification
1. Report, in plain terms, exactly which of the 3 steps (if any) returned a 2xx, and the exact
   status/body for every step that was actually attempted (not just the first failure — if step 1 fails,
   report its exact error before moving to step 2, and so on).
2. If any step succeeds: use a fresh HIP (not one of Pooja's already-poisoned pending requests) and
   confirm a newly-raised self-view PATRQT request actually resolves to GRANTED in
   `repo/storage/consents.jsonl` shortly after — the real end-to-end proof, not just the setup call
   succeeding.
3. If all 3 fail, report each exact error and stop — don't try a 4th guess without checking back in.

## MANDATORY, NON-NEGOTIABLE verification — unchanged, still required once ANY step above succeeds
Aayush's own words: *"i dont want to auto aprove doctor request that is the main point."*
`ensure_self_view_auto_approve()` scopes the policy narrowly — `purpose_code="PATRQT"` always,
hardcoded, never `CAREMGT` — and spec §6.13's own text (*"This includes the list of HI types, the
purpose and a date range between the policy will be active"*) states a future consent request must
match the policy's purpose to auto-approve, not just come from the same HIU. This is a reading of the
API's documented shape, not yet confirmed against a live ABDM response. **Once any step above succeeds
(2xx) for the first time**, before considering this feature safe to leave active even in the sandbox:
raise a real doctor consent request (`purpose_code="CAREMGT"`, e.g. via the existing Dr. Riya Trivedi
test flow) against the SAME patient/HIP the self-view policy now covers, and confirm it still comes back
as a normal pending request in the Requests tab, requiring the patient's own manual Approve click via
P8's picker — NOT auto-granted. If it DOES auto-grant, stop and report it immediately rather than
shipping anything further on top of this policy — it would mean every doctor consent for this
patient/HIP is now silently pre-authorized, which is exactly what must not happen.
