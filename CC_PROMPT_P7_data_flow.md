# CC Prompt — Data Flow (spec §7): view real health-record content for a granted consent

**Model recommendation: Sonnet, extended thinking ON.** New territory for this project — the first
chunk where `aegle-phr` calls INTO `repo/`'s own already-working code at runtime (not just reads it
for reference), plus a real async polling UI and several genuine error paths (see below). Worth the
extra care.

## Why this chunk looks different from every other chunk so far — read this before touching code

Every one of §7 Data Flow's 5 ABDM endpoints requires an `X-HIU-ID` header and NONE of them take a
patient session token (`X-AUTH-TOKEN`) — confirmed directly against the spec (§7.3.1-7.3.5). This is
architecturally different from Consent/Links/Provider-Directory, which are all either patient-session
calls or session-less global lookups. **The patient's own PHR app literally cannot call these
endpoints as "itself"** — it has no HIU registration of its own to send.

This doesn't mean Data Flow is out of scope. It means the entity that DOES have HIU capability is
already sitting right next to this project: `repo/server/hiu_consent.py`'s own docstring calls its
identity **"our HIU identifier"** — this project's one shared ABDM client (`SBXID_046112`) already has
HIU capability registered, and `repo/server/hiu_health_information.py` already implements the entire
§7 flow against it (request → on-request ack → HIP data push → decrypt → notify), fully working,
proven live: `repo/storage/hiu_health_information.jsonl` already has real decrypted FHIR content in it
right now (Conditions, MedicationRequests, Procedures) from an actual sandbox round trip.

**Confirmed with Aayush directly (2026-09-01): this chunk reuses that existing code by having
`aegle-phr` import and call it at runtime**, rather than duplicating the ECDH/decrypt pipeline a
second time inside `aegle_phr`. This is a genuine, deliberate, one-time exception to "never touch
`repo/`" — but the exception is narrow: **read AND CALL `repo/`'s existing functions, never MODIFY
any file under `repo/`.** If something here seems to need a change to `repo/` itself, stop and flag it
rather than editing it.

## The exact mechanism to reuse (all in `repo/server/`, already built, already working — do not
re-implement any of this)

- `hiu_health_information.py`'s `initiate_health_information_request(hiu_id, consent_id, hip_id,
  date_range_from, date_range_to)` — POSTs the request, generates fresh ECDH key material internally,
  saves a pending session, returns a `requests.Response` (202 expected) with an extra
  `response.aegle_request_id` attribute (our own REQUEST-ID, needed for the next step). Raises
  `DateRangeValidationError` (a `ValueError` subclass, imported from the same module) if the requested
  range falls outside the consent's own approved `permission.dateRange` — checked locally, no ABDM
  call wasted on a range that would just get rejected async anyway.
- `server/callbacks/repository/pending_health_information_request_repository.py`'s
  `get_pending_health_information_request(request_id)` — returns the pending session dict; once the
  on-request callback has landed (asynchronously, on `repo/`'s own already-registered callback route,
  nothing new to wire up here), this dict gains a `transaction_id` key.
- `server/callbacks/repository/hiu_health_information_repository.py`'s
  `get_hiu_health_information(transaction_id)` — returns `None` until the HIP's data push (and its
  final notify) has fully landed; once populated, returns `{"care_contexts": {care_context_reference:
  {"hi_status", "description", "bundle", "received_at"}, ...}, ...}` — `bundle` is the actual decrypted
  FHIR content for that care context.
- **The precondition that makes this all work**: `validate_date_range_against_consent()` (called
  internally by `initiate_health_information_request()`) reads the consent artefact from `repo/`'s OWN
  local cache (`hiu_consent_repository.get_hiu_consent(consent_id)`) — populated only when
  `repo/server/hiu_consent.py`'s own CLI flow ran its "Consent Fetch" step for that specific consent.
  **This means "Fetch my records" will only work for a consent that was raised AND fetched through
  that CLI flow** — not just any consent that happens to show as GRANTED in aegle-phr's own live
  ConsentScreen (which reads straight from ABDM, independently of `repo/`'s local cache). If
  `get_hiu_consent()` returns nothing, surface a clear, specific message ("no local record of this
  consent — was it raised and fetched via `repo/server/hiu_consent.py`?"), don't let it crash
  unhelpfully or look like a generic failure.

**Correlation chain to poll** (mirror `repo/tools/m3_test_suite/flows/health_information_request.py`'s
own working reference implementation — read it in full before building, it's the exact sequence
already proven live): call `initiate_health_information_request()` → get `response.aegle_request_id`
→ poll `get_pending_health_information_request(request_id)` until it carries a `transaction_id` → poll
`get_hiu_health_information(transaction_id)` until it's non-`None` → render `care_contexts`. Do NOT
port the CLI's own `wait_for_callback()` (that's a CLI-specific mechanism that watches capture files
synchronously) — for a web backend, plain repeated reads of the two repository functions above, on a
short interval, is simpler and correct, since they're just file-store reads.

## What to build

### Backend: new module `aegle_phr/phr/data_flow.py`
Two functions, each lazily importing from `server.*` inside the function body (NOT at module import
time) and catching `ImportError` with a clear message — **`aegle_phr` must keep working standalone for
every OTHER feature even when `repo/` isn't present/mounted; only this module's two functions need
`repo/` at runtime, and they should fail obviously and helpfully, not with a bare traceback, when it
isn't there** (e.g. aegle-phr run on its own instead of mounted into `repo/server/main.py`):

- `request_health_information(consent_id, hip_id, hiu_id, date_range_from, date_range_to)` — calls
  `initiate_health_information_request()`, catches `DateRangeValidationError` and returns a clear
  error shape for it, returns `{"request_id": ..., "status_code": ...}` on success (202).
- `get_health_information_status(request_id)` — implements the polling/correlation chain above in one
  call (looks up the pending session, then the stored health information if a transaction_id exists),
  returns one merged status object the frontend can poll: something like `{"phase": "pending" |
  "transaction_assigned" | "complete", "transaction_id": ..., "care_contexts": {...} | null}`.

Add two small routes wherever `consent.py`'s routes are wired into `build_router()` — a `POST` to
trigger, a `GET .../status/{request_id}` to poll. No new headers/host/encryption concerns here at all
(this module makes no direct ABDM calls itself — it's a thin wrapper over `repo/`'s already-working
code) — don't apply the CERTIFICATES.md rule here, it doesn't govern this module.

### Frontend: extend `ConsentScreen.tsx`'s existing Level-3 artefact detail view — do NOT build a new dedicated screen
This is a deliberate exception to the "give each feature its own screen" pattern Consent/Provider
Directory both used — Data Flow's natural home is right where a specific granted consent's own HIP +
care contexts are already shown (Level 3 of Consent's own drill-down), not a separate screen someone
has to navigate to and re-select the same consent in. Add a "Fetch my records" action there, using
that SAME artefact's own `hip.id`/`hiu.id`/`consentId`/`permission.dateRange` fields — the exact same
fields `select_granted_consent()` in the CLI reference reads — to call the new POST route, then poll
the GET status route every few seconds (a short, bounded number of attempts with a clear timeout
message, not an infinite loop) until `care_contexts` appears. Render each care context's `bundle`
(the decrypted FHIR content) — reuse the existing `RawBody` component for the full bundle dump (this
is a testing harness, raw FHIR JSON is legitimate, useful content to show, not something to hide), but
give each entry a short human header first (resourceType counts, hi_status) using whatever `Card`/
`Badge` primitives the design-overhaul chunk already established, so it doesn't look like a wall of
JSON with nothing else. An entry with `hi_status` other than `"OK"` should render distinctly (its
`description` explains why) rather than looking like a successful result.

## What's explicitly NOT in scope
- **No changes to any file under `repo/`.** If you find yourself wanting to edit something there,
  stop and flag it instead.
- Not building §7.3.3/§7.3.4 ("Notify HIP"/"Notify HIU") — those already happen automatically inside
  `repo/`'s own already-working push-receive pipeline; nothing new needed.
- Not building §7.3.5 (the raw ABDM "request status" GET) — polling `repo/`'s own local repository
  state (above) is simpler, needs no new headers, and reflects the actual data faster than a
  round trip to ABDM would.
- No duplicated ECDH/crypto code anywhere in `aegle_phr` — all of that stays exactly where it already
  works, in `repo/server/fidelius_crypto.py`, called only via `repo/`'s own existing functions.
- Doesn't touch Consent's Approve blocker (separate, still-unbuilt chunk) or Provider Directory.

## Verification
`repo/storage/hiu_health_information.jsonl` already has at least one real, complete, successful
transaction from a prior CLI run — find that consent (via `repo/server/callbacks/repository/
hiu_consent_repository.py` or by re-reading the CLI's own output/logs if still around) and use IT
first to sanity-check the new UI path end-to-end without needing a brand-new live HIP push (which
takes real round-trip time and depends on the HIP's own server being reachable). Once that works,
try a genuinely fresh consent (raised + fetched via `repo/server/hiu_consent.py`'s CLI flow first, per
the precondition above) to confirm the full live path, not just the already-populated case. Report
which of the two module-docstring-flagged judgment calls in `hiu_health_information.py` (request body
shape; outbound key format) held up, if either mattered for whatever you tested against.
