# CC Prompt — Provider Directory (spec §10.3.13-15: all-providers / provider-by-provider-id / govt-programs)

**Model recommendation: Sonnet, extended thinking OFF.** This is the simplest remaining chunk in the
project so far — three stateless, read-only GETs, no patient session token involved, no encryption,
shapes fully confirmed against both the spec PDF and Postman with matching real headers. No live-data
ambiguity like Consent had. Extended thinking isn't buying anything here; keep it fast.

## Where this fits

Chosen as the next chunk (over Data Flow / Scan-and-Share / the Consent Approve-picker) specifically
because it's the lowest-risk, quickest win, and fully independent of everything else. It does NOT by
itself unblock Consent's disabled Approve button — that needs a picker built from your own Linked
Records data (a separate, not-yet-built chunk) — don't conflate the two.

**Run this AFTER the visual/design overhaul chunk (`CC_PROMPT_DESIGN_v1_visual_overhaul.md`) if that's
already landed** — build this screen using whatever shared primitives that chunk creates (`Card`,
`Button`, `PageHeader`, `EmptyState`, `CardGrid` under `src/components/ui/`) so it's consistent with
the rest of the app from day one, not something that needs restyling later. If the design overhaul
hasn't been run yet when you pick this up, don't block on it — build with the existing `styles.css`
patterns for now rather than inventing a third one-off style, and note in your report which case you
were in.

## Confirmed directly against the spec (§10.3.13-15) and Postman's "User Initiated Linking" folder — no gaps between them this time

All three are `GET`, under `settings.abdm_gateway_base_url` (already `https://dev.abdm.gov.in/api/
hiecm/gateway/v3` in `.env` — note this is a DIFFERENT, more specific base than `abdm_hiecm_base_url`
that Links/Consent use, don't reuse that one here). No encryption — same HIE-CM-family exemption as
Links/Consent/UIL (see `CERTIFICATES.md`).

**Headers — genuinely different from the Links/Consent/UIL family, confirmed in both places**: only
`REQUEST-ID` + `TIMESTAMP` + `X-CM-ID` (`settings.abdm_x_cm_id`) are listed as required in the spec's
own header table for all three endpoints — notably NOT `Authorization`, and NOT `X-AUTH-TOKEN` at all
(makes sense: these are global directory lookups, not tied to a specific patient session). Postman's
saved requests each carry a `bearer` auth block (`{{BEARER_AUTH}}`) the same way every other HIE-CM
family does, but that's Postman's own collection-level default, not necessarily proof the live API
enforces it — and Postman's own visible header list for these three, like the spec, does NOT include
Authorization or X-AUTH-TOKEN explicitly either. **Build `_headers()` to include `Authorization:
Bearer {get_gateway_token()}` anyway** (matches the safe default used everywhere else in this app,
and costs nothing to include if unneeded) but do NOT add `X-AUTH-TOKEN` — there is no patient session
token parameter to these calls at all. If a live call 401s/403s, the first thing to check is whether
Authorization needs to be dropped entirely, not added to.

### 1. All providers (§10.3.13)
`GET {abdm_gateway_base_url}/providers?stateCode={stateCode}&districtCode={districtCode}&name={name}`
— searches providers (HIPs/HIUs/health lockers) by name. The spec's own example uses
`stateCode=-1&districtCode=-1&name=test` — `-1` appears to mean "any"/unfiltered for the code
params; there's no ABDM state/district code lookup list anywhere in this project, so build the UI
around free-text name search only, always sending `stateCode=-1&districtCode=-1` (don't build a
state/district picker — there's nothing to source its values from). Confirmed response (both spec and
Postman agree, no saved live example but the documented shape is detailed and specific) — an ARRAY:
```json
[{
  "identifier": {"name": "DRiefcase Health Locker", "id": "driefcasehl"},
  "facilityType": ["HIP", "HIU", "HEALTH_LOCKER"],
  "isHIP": true,
  "isGovtEntity": false,
  "endpoints": {"healthLockerEndpoints": [{"use": "registration", "connectionType": "HTTPS", "address": "https://..."}]}
}]
```
`endpoints` is often just `{}` in the example set — treat it as optional/display-if-present.

### 2. Provider by ID (§10.3.14)
`GET {abdm_gateway_base_url}/providers/{providerId}` — single provider detail. Confirmed response, a
single object (not wrapped, not an array):
```json
{"identifier": {"name": "DRiefcase Health Locker", "id": "driefcasehl"}, "facilityType": ["HIP","HIU","HEALTH_LOCKER"], "isHIP": true}
```
The example shown is a strict subset of #1's own per-item shape (missing `isGovtEntity`/`endpoints` in
the doc's own example) — likely just a documentation shortcut, not a guarantee those fields are
absent live. Parse defensively either way, same convention as every other module in this app.

### 3. Government programs (§10.3.15)
`GET {abdm_gateway_base_url}/govt-programs` — no query params. Confirmed response, an ARRAY:
```json
[{"identifier": {"name": "AB - PMJAY", "id": "PMJAY"}, "facilityType": ["HIP"], "isHIP": true}, ...]
```
Note Postman's own saved request name for this is literally `all-govt-programs`, in a DIFFERENT
Postman folder ("Gateway", not "User Initiated Linking" where the other two live) — same headers,
same base URL, no functional difference, just filed differently in the collection. Doesn't matter for
implementation, worth knowing if you go back to Postman later and can't find it where you expect.

## What to build

### Backend: new module `aegle_phr/phr/providers.py`
Mirror `links.py`'s `_headers()`/`_execute()` pattern (private headers builder + a call wrapped in
`call_with_retry()`, archived via `call_log.archive()`) — same as every PHR module so far — but with
the headers difference above (no `X-AUTH-TOKEN` param to thread through at all, since none of these
three calls take one). Three functions:
- `search_providers(settings, name: str, state_code: int = -1, district_code: int = -1) -> AbdmResult`
- `get_provider(settings, provider_id: str) -> AbdmResult`
- `get_govt_programs(settings) -> AbdmResult`

Same `AbdmResult` passthrough convention as every other module — return ABDM's raw response body,
Pydantic response models are documentation-only contracts, never used to gate/validate the actual
response (same reasoning as always: an unexpected live shape should never cause a misparse, only a
documented gap). Add the three route handlers to whatever router `links.py`'s route lives in (or a
new small router file if that's cleaner — your call, follow whatever pattern is already established
for wiring a new module's routes into `build_router()`).

### Frontend: new screen, e.g. `ProviderDirectoryScreen.tsx`
A dedicated screen (not inline on Home — this is a distinct, self-contained feature, same reasoning
as Consent getting its own screen), reachable from the signed-in nav (`App.tsx`) — add a nav entry,
e.g. "Providers", alongside Profile/Consent Manager/Logout. Two sections:
1. **Search Providers** — a name search box (free text, defaults to something reasonable like an
   empty/placeholder query so the screen isn't blank on first load — try `name=""` first; if ABDM
   rejects an empty name, fall back to requiring at least one character typed before searching, and
   note which case it turned out to be in your report) + results rendered as cards (provider name,
   id, facility type badges HIP/HIU/HEALTH_LOCKER, a govt-entity indicator if `isGovtEntity` is
   true). Use `CardGrid` if the design system chunk has landed, so results render as even-sized cards
   — this endpoint returning ~15 example entries in the sandbox is exactly the kind of list where
   uneven card sizing would be visible.
2. **Government Programs** — fetched on screen load (or via a refresh button), rendered as its own
   card list, same visual treatment as the search results.

Optionally: clicking a search result card can call `get_provider(id)` to show a "full detail" view —
nice-to-have, not required, since #1's own response already contains everything #2 documents. Don't
over-build this if the two shapes turn out identical live; a plain expand-in-place of the already-
fetched card data is enough unless you find #2 genuinely returns more.

## What's explicitly NOT in scope here
- Does not touch Consent's disabled Approve button — that's a separate chunk (a HIP+care-context
  picker sourced from Linked Records, not from this global directory).
- No state/district code picker — there's no source for those values anywhere in this project.
- No change to any other screen, API call, or routing beyond adding this one new route + nav entry.
- Don't touch `repo/`. No git commit/push/init. Never print secrets into your report.

## Verification
These are stateless and global — no need to raise a real consent request or have existing linked
records to test this, unlike Consent. Test with the spec's own example query (`name=test`) and expect
to see the DRiefcase-family sandbox entries; also test a name that matches nothing (confirm the
`EmptyState` renders cleanly, not a blank screen) and the empty/default-load case. Report which
headers actually worked live (particularly whether Authorization was needed/rejected) since the spec
and Postman didn't agree on whether it's required, and note the same for a search with an empty name.
