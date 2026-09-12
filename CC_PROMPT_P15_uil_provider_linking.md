# P15 — User-Initiated Linking (spec §10.1–§10.12), the "Find my records" flow

Aayush's own instruction (2026-08-31, amendment three): *"UIL will be my last step... the first thing
I want to implement is being able to see all the linked data to my account."* Everything else got
built first, in the order he chose. He's now explicitly asking for this one.

**Model recommendation: Sonnet, extended thinking ON.** Same reasoning as the original UIL research
(`CC_PROMPT_P3_provider_search_and_uil.md`, still in this repo, superseded by this file): new inbound-
callback infrastructure, a new correlation/state table, and the first live async round trip in this
app where your own outbound call and an ABDM-delivered inbound callback have to correlate correctly.

## Re-verified against the current repo before writing this — a lot has changed since P3 was drafted

P3 was written 2026-09-01, before P8 through P14 shipped. Re-checked directly (grep + `cat`, not
memory) right before writing this prompt. Three things P3 assumed still need building are **already
done**; one thing P3 recommended is **now the wrong pattern** given what the rest of the app does
today:

1. **Provider Search (§10.3.13–§10.3.15) is 100% built already** — `aegle_phr/phr/providers.py` has
   `search_providers()`, `get_provider()`, `get_govt_programs()`, and `testui/src/routes/
   ProviderDirectoryScreen.tsx` already renders a working search UI at `/providers`. **Do not rebuild
   this.** This chunk's only job regarding provider search is to give it (or a similar picker) a real
   entry point into the linking flow below — see "What to build," step 4.

2. **The three inbound callback paths are already registered, but archive-only** —
   `aegle_phr/callbacks/router.py`'s `CALLBACK_ROUTES` already has
   `/api/v3/hiu/patient/care-context/on-discover`, `on-init`, `on-confirm` wired through the generic
   `dispatch()` archiver (its own comment literally says "Real per-callback handling lands in P3,
   against real captures" — that's this chunk). **Extend, don't replace**: add a new
   `aegle_phr/callbacks/uil_services.py` (mirroring `subscription_services.py`'s shape exactly — one
   `handle_*` function per callback type) and a `_UIL_HANDLERS` dict in `router.py`, called the same
   way `_SUBSCRIPTION_HANDLERS` already is, right after `dispatch()` archives the payload. Do not
   touch `dispatcher.py`'s own "never raise" contract.

3. **This app's actual persistence pattern is Postgres, not the file-based `json_file_store.py` P3
   suggested mirroring from `repo/`.** Every other async chunk built since P3 was written (P13's
   Subscription Flow) uses a real ORM table + a plain-functions repository module —
   `aegle_phr/models.py`'s `SubscriptionRequest` + `aegle_phr/phr/subscription_repository.py`. **Do
   the same here**: add a new `UilLinkRequest` model to `models.py` (columns: `id`, `request_id` —
   your own `REQUEST-ID` header value, the correlation key on the way out; `stage` — `"discover"` /
   `"link_init"` / `"link_confirm"`; `hip_id`; `abha_address`; `status`; `detail` (JSONB, the latest
   callback body or error); `link_ref_number` — populated once on-init arrives, needed for the confirm
   call; timestamps) and `aegle_phr/phr/uil_repository.py` (plain functions over `session_scope()`,
   same shape as `subscription_repository.py` — `save_new_request()`, `get_by_request_id()`,
   `update_status_by_request_id()`, etc.). This also directly solves the frontend's polling
   requirement below — poll a route that reads this table.

4. **The new visual primitives from P14 exist and must be used for every new screen this chunk adds** —
   `ProfileHeader`, `InfoRow`/`KeyValueCard`, `ListRow`, `SegmentedControl`, `EmptyState`, `Card`,
   `Button`, `Badge` all live in `testui/src/components/ui/`. **Do not use `<fieldset>`/`<legend>`
   anywhere in this chunk** — that pattern is being retired app-wide (P14 already dropped it from 70
   uses to 9 remaining). A care-context match from discover, or a linked-facility row, is a `ListRow`
   or a `Card`, not a fieldset.

## The X-HIU-ID question — no longer a total unknown, but still not proven for THIS specific family

P3 flagged this as genuinely unresolved and refused to guess. Since then, **every other HIU-role call
built in this app has consistently used `CLIENT_ID` (`SBXID_046112`) as "our own HIU identity"** —
confirmed independently in Data Flow's self-view fetch (`aegle_phr/phr/data_flow.py`), Subscription
Flow's self-subscription (`aegle_phr/phr/subscription.py`, and re-confirmed a third way via Postman's
own template variable name for that exact field), and Consent Auto-Approval's own `hiu.id` correction.
This project's own standing architecture decision (`ONE client ID, one callback URL` — see the
project's own memory, "Decisions Aayush locked in," #2) is exactly why this keeps being the answer.

**So: use `settings.abdm_hiu_id`, and set its default/recommended value to `CLIENT_ID` when building
this — but still flag it for live confirmation before the OTP-consuming step (link-init), the same
way this project has flagged and then confirmed the same value for two other spec sections already.**
`.env`/`.env.example` currently has `ABDM_HIU_ID=` blank with a comment saying it's unconfirmed —
update that comment to reflect the CLIENT_ID pattern once you set it, rather than leaving it reading
as a total unknown when it isn't anymore.

## Everything else from P3's research still holds — re-read it, don't re-derive it

Open `CC_PROMPT_P3_provider_search_and_uil.md` in this repo and read it in full before building — its
header conventions (`Authorization` + `X-AUTH-TOKEN` — note the literal name, not `X-token` — +
`X-CM-ID` + `X-HIU-ID` + `REQUEST-ID`/`TIMESTAMP` for the three outbound UIL calls only), the
confirmed base URLs (`HIECM_BASE_URL = https://dev.abdm.gov.in/api/hiecm`, path family
`/user-initiated-linking/v3/...`), the "no encryption anywhere in this family" finding (flag for live
verification, same as before — this project has been burned by wrong certificate/encryption
assumptions more than once), the three outbound call shapes (discover / link-init / link-confirm) and
their three corresponding inbound callback shapes (on-discover / on-init / on-confirm), and the router-
collision check against `repo/`'s HIP-facing paths (already confirmed clear, don't re-verify) are all
still accurate and don't need re-research. The only things this file changes are: skip rebuilding
provider search, use the Postgres repository pattern instead of file-based storage, use the new P14 UI
primitives, and treat X-HIU-ID as "very likely CLIENT_ID, confirm before OTP" rather than "totally
unknown."

## What to build

1. `aegle_phr/phr/uil.py` — `discover(settings, x_token, hip_id, abha_address)`,
   `link_init(settings, x_token, transaction_id, patient_matches)`,
   `link_confirm(settings, x_token, token, link_ref_number)`. Same per-module `_headers()`/`_execute()`
   shape as every other module in `aegle_phr/phr/` (duplicate the small helpers — established
   convention, don't import across modules).
2. `aegle_phr/models.py` — new `UilLinkRequest` model. `aegle_phr/phr/uil_repository.py` — plain
   functions over it, mirroring `subscription_repository.py`.
3. `aegle_phr/callbacks/uil_services.py` — `handle_on_discover()`, `handle_on_init()`,
   `handle_on_confirm()`, each updating the matching `UilLinkRequest` row by `request_id` from the
   callback's `response.requestId`. Wire these into `router.py`'s existing three archive-only routes
   via a new `_UIL_HANDLERS` dict, called the same way `_SUBSCRIPTION_HANDLERS` already is.
4. A polling result route (e.g. `GET /phr/uil/result?requestId=...`) reading the `UilLinkRequest` table
   — the frontend polls this every 2-3s for a bounded window (~30s) after each outbound call, same
   pattern P9's self-view waiting state already established on the frontend (`SelfViewWaitingCallout`
   is the reference — reuse its look/feel, don't invent a new waiting-state pattern).
5. Frontend, one continuous flow, entry point from the existing `/providers` screen (add a "Link this
   facility" action per result, using the P14 button hierarchy — one solid primary action, matching
   the reference app's "Link new facility" pattern) →
   - Review step: show the discovered care contexts (from on-discover's callback body) as `ListRow`s
     or `Card`s (per what the content actually looks like — a HIP name + a few care-context rows,
     probably `Card` with `ListRow` children) with a clear "select which to link" or "link all" action.
   - Link-init, with explicit go-ahead before the call fires (this triggers a REAL OTP to the
     patient's real phone via the HIP — same live-testing caution as every other OTP call in this
     project).
   - OTP entry screen, matching this app's existing OTP-entry UI conventions (there are several
     already, e.g. `LoginScreen`'s mobile-OTP step, `MobileLoginScreen` — copy that pattern, don't
     invent a new OTP input component).
   - On confirm success: route back to `/home` (or wherever "Linked Records" already renders) and
     trigger a refetch of `getAllLinkedRecords()` — the newly-linked care context will just appear
     there, since linking is pure metadata with no special-casing by how it was linked (confirmed
     repeatedly elsewhere in this project). Don't build a second, separate "linked via UIL" view.
   - A visible timeout state if a callback doesn't arrive within the poll window (per every prior
     async chunk's own convention) — never an infinite spinner.

## Explicitly NOT in scope for this chunk

Anything about consent (§6) — UIL's job stops at linking care contexts, not requesting access to the
data inside them; a freshly-UIL-linked HIP still needs its own self-view consent (P9's existing
auto-provisioning logic already handles this automatically once the HIP shows up in Linked Records —
no new code needed here). Actually reading/displaying record content — that's Data Flow (§7),
already built. HIP-side changes of any kind — `repo/` stays read-only reference.

## Constraints (standing, unchanged)

Never delete/truncate `logs/`/`storage/` content. Don't modify any file under `repo/` — if
`discover_service.py`/`link_init_service.py`/`link_confirm_service.py` on the HIP side don't behave as
expected during live testing, report exactly what happened, don't patch `repo/` to make it pass. No
git commit/push/init. Never print the access key, client secret, plaintext OTP, mobile number, email
address, password, or any live token into any report. Real-app navigation is not optional — this flow
must be reachable from somewhere a logged-in user would actually find it, not a route they have to
already know the URL for.

## Verification

Offline: read every new file back; confirm the new callback handlers are wired the same way
`_SUBSCRIPTION_HANDLERS` is; confirm the new `UilLinkRequest` table's `request_id` column actually
matches what's sent as the `REQUEST-ID` header on each outbound call; confirm no `<fieldset>` was
added anywhere in this chunk; screenshot the new screens at phone width and compare against the
existing app's own established look (P14's screens), not the ABDM reference screenshots again — this
chunk isn't a design pass, it's new functionality using an already-approved design.

Live (ask permission before each step — this is the first chunk to depend on a second local server,
`repo/`'s own HIP callback handling, being up and reachable via the same ngrok tunnel, and it consumes
a real OTP partway through):
1. Provider search — already working, just confirm the new "Link this facility" entry point reaches
   the discover call correctly.
2. Confirm `X-HIU-ID = CLIENT_ID` actually works for discover before proceeding — if ABDM rejects it,
   stop and report the exact error rather than guessing a second value.
3. Discover against your own HIP (`IN3310002215`, "Aayush Health Care") using a real ABHA address that
   has actual records there — confirm on-discover arrives and correlates via `request_id`.
4. Link-init only with explicit go-ahead (real OTP) — confirm on-init arrives with a usable
   `linkRefNumber`.
5. Link-confirm with the real OTP — confirm on-confirm arrives and the newly-linked facility shows up
   in the existing Linked Records view on Home without any new code path.
