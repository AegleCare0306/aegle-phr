# CC PROMPT P22 — Scan & Share (PHR app side, `aegle-phr`)

**Target repo:** `aegle-phr` (plus its `testui/`). **Do not touch `repo/` or `aegle-abdm-core`.** P21 already built the HIP side in `repo/`; this chunk is the other end of the same handshake and must not modify it.

**Recommended model:** **Opus, extended thinking ON.** Three of the four ABDM responses in this chunk have **no saved example anywhere** — not in the spec, not in Postman, not in NHA's reference wrapper — so the code has to be written to survive shapes nobody has seen yet, and there is a real fork (callback vs. polling) that has to be built both ways rather than guessed. There is also a React screen with QR decoding.

**Chunk number:** P22. P21 is the HIP side (`repo/CC_PROMPT_P21_scan_and_share_hip.md`) — read its §3 before starting; it is the authoritative wire contract for the other end of this flow and is not repeated here.

---

## 1. Why this chunk exists

P21 built the facility side: it receives a shared profile, issues a queue token, and acknowledges. It is testable today only by opening ABDM's own hosted page at `phrsbx.abdm.gov.in/share-profile`.

Aayush has no way to scan a QR code. This chunk builds the patient end so the loop closes on one machine: **our own PHR app scans (or accepts) the counter QR, shares the profile, and shows the token number back** — while P21's token board shows the same token on the facility side. One server, one tunnel, both halves.

Verified state of `aegle-phr` as of 2026-09-29, read from the working tree:

| Fact | Evidence |
|---|---|
| No Scan & Share anywhere | `aegle_phr/api.py` has no share route; the only `qr`-related route is `/phr/profile/qr-code` (SS3.40, the patient's **own** ABHA QR — unrelated). |
| `/api/v3/hiu/patient/on-share` is registered but does nothing | `aegle_phr/callbacks/router.py` `CALLBACK_ROUTES`: `("/api/v3/hiu/patient/on-share", "on_share")`, and its own comment — `"on_share remains archive-only, no chunk has built it yet"`. It is in no handler dict. |
| Alembic head is `f6a7b8c9d0e1` | `alembic/versions/20260923_0006_f6a7b8c9d0e1_create_locker_hiu_tables.py` is the newest of 6. |
| `X-HIU-ID` must be the PHR facility id | `aegle_phr/phr/uil.py`'s own banner, live-settled 2026-09-23: `SBXID_073333` (bridge/client id) → **400 "Invalid HIU ID"**; `IN3310002290` (PHR facility id) → **202** plus a real callback. `settings.abdm_hiu_id` holds it. |
| The test UI already has a slot for this | `testui/src/components/ui/BottomNav.tsx` supports one `raised` circular tab, described in its own docstring as *"the reference app's QR-scan treatment"*. `App.tsx` currently gives that slot to Consent with a comment saying *"nothing in this app is a closer match"* — which stops being true in this chunk. |
| No QR library | `testui/package.json` dependencies: `lucide-react`, `react`, `react-dom`, `react-router-dom`. Nothing that decodes a QR. |

---

## 2. What the patient experiences

```
1. Pooja is logged into our PHR app. She taps the Scan tab.

2. She points the camera at the QR taped to Aegle Urgent Care's reception desk
   (or uploads a photo of it, or pastes the URL -- all three, see 4.7).
   The QR encodes:
       https://phrsbx.abdm.gov.in/share-profile?hip-id=IN2410002590&counter-id=OPD-1
   OUR APP PARSES THAT URL. It does not open it. The QR is ABDM-standard so any
   PHR app can read it; ours is just another reader.

3. The app shows: "Share with Aegle Urgent Care?" and lists exactly what goes --
   name, ABHA address, gender, date of birth, phone, address. Nothing hidden.

4. She taps Share. The app calls the CM.

5. The CM forwards it to the facility (that is P21). The facility issues token 0007.

6. Her screen shows: "Token 0007 -- Aegle Urgent Care -- valid 30 minutes".
```

Step 6 is the hard part of this chunk, because **nobody has documented how the token gets back to the patient app.** See §3.3.

---

## 3. The wire contract

### 3.1 Outbound: share the profile

`POST {settings.abdm_hiecm_base_url}/patient-share/v3/share`

Headers — read off our own PHR Postman collection (`Patient Share / 01 profile-share`) verbatim:

```
REQUEST-ID:    <ours>
TIMESTAMP:     <ours>
X-CM-ID:       sbx                  <- settings.abdm_x_cm_id
X-HIU-ID:      IN3310002290         <- settings.abdm_hiu_id, THE PHR FACILITY ID
X-AUTH-TOKEN:  <the patient's session token, RAW>
Authorization: Bearer <gateway token>
Content-Type:  application/json
```

`X-AUTH-TOKEN` is the literal header name and the value is passed **raw, with no `Bearer ` prefix** — exactly as `uil.py`'s `_headers()` does it. (`repo/server/linking.py`'s commented-out, never-run discover prefixes it with `Bearer`; that code has never executed. Follow `uil.py`, which has.)

Body — the same shape P21 receives, which is the point: we are the sender of what it parses. P21 §3.1 has both verbatim samples. Build it from the patient's own profile:

```json
{
    "intent": "PROFILE_SHARE",
    "metaData": {
        "hipId": "<hip-id from the QR>",
        "context": "<counter-id from the QR>",
        "hprId": null,
        "latitude": null,
        "longitude": null
    },
    "profile": {
        "patient": {
            "abhaAddress": "...",
            "abhaNumber": "...",
            "name": "...",
            "gender": "M",
            "dayOfBirth": "15",
            "monthOfBirth": "01",
            "yearOfBirth": "1984",
            "address": {"line": "...", "district": "...", "state": "...", "pincode": "..."},
            "phoneNumber": "..."
        }
    }
}
```

- `metaData.hipId` and the QR's `hip-id` are the same value. Send it in both places; that is what both samples do.
- `hprId` / `latitude` / `longitude` are the **facility's** practitioner and location, which a patient app does not have. **UNCONFIRMED whether they may be omitted or must be present-but-null.** Omit them from the JSON entirely on the first attempt; if ABDM 400s complaining, send explicit nulls. Record which worked in a code comment.
- `abhaNumber`: **omit the key entirely when the profile has no ABHA number** — our own Postman sample has it commented out, so absent is known-legal. Do not send `null`.
- `address.pincode` — lowercase on the way out. P21 reads both spellings inbound, so either is safe, but match our own collection.

### 3.2 Expected response

**UNCONFIRMED — there is no saved example response for this call anywhere.** Our Postman collection has zero saved responses on it; NHA's wrapper implements only the HIP side of this flow, not the patient side.

Every comparable patient-authenticated call in this project returns a bare `202 Accepted` with nothing useful in the body (see `uil.discover()`'s own docstring). Assume that, **but do not depend on it**: store the response body verbatim and parse nothing from it beyond what is actually present. Treat any 2xx as "accepted", and mark it `UNCONFIRMED:` in the code.

### 3.3 How the token comes back — the real open question

Two candidate mechanisms. **Build both.** This is exactly the case Aayush's standing rule covers: when sources conflict or go silent, build and test rather than pick.

**Candidate A — a callback to us.** `POST /api/v3/hiu/patient/on-share`, already registered and archive-only. Its path came from a task spec, not from a captured call, and **no payload shape for it exists anywhere**. Wire a real handler that:

- archives verbatim (`dispatch()` already does this — do not change that),
- correlates on `response.requestId` if present (the convention every other callback in this project follows),
- **falls back to correlating on `abhaAddress` + `context`** against the most recent PENDING row when there is no `response.requestId`, because we genuinely do not know this payload's envelope,
- reads a token number from whichever of these is present, in this order: `acknowledgement.profile.tokenNumber`, `profile.tokenNumber`, `tokenNumber` — P21's outbound ack uses the first, and the CM may pass it through unchanged, reshape it, or not send it at all,
- logs loudly and stores the raw payload when it can find no token, rather than failing silently. **That log line is the deliverable if Candidate A turns out not to exist.**

**Candidate B — we poll.** `GET {hiecm}/patient-share/v3/profile/getTokenDetails?limit=-1`

Headers, from our Postman collection verbatim: `REQUEST-ID`, `TIMESTAMP`, `X-CM-ID`, `X-AUTH-TOKEN`, `Authorization: Bearer`. **No `X-HIU-ID`** on this one — it is absent from the saved request, so do not add it.

Response shape **UNCONFIRMED**, zero saved responses. Return it to the UI verbatim and let the screen render defensively (§4.7).

**Which one the UI trusts:** Candidate B, the poll, because it is at least a documented endpoint. Candidate A updates the same row when it fires, so whichever arrives first wins and the UI shows the token either way. Make that precedence explicit in a comment — it is a deliberate choice under uncertainty, not an accident.

---

## 4. What to build

Follow the conventions already in this package rather than inventing new ones. `aegle_phr/phr/uil.py` + `uil_repository.py` + `callbacks/uil_services.py` + their four `api.py` routes are the closest existing analogue in every respect — same header family, same 202-then-callback shape, same poll-a-row frontend mechanism. **Read all four before writing anything.** Per this package's own stated convention (see `subscription.py`'s banner), each module carries its own `_headers()` / `_execute()` rather than importing a shared one. Duplicate, do not refactor.

### 4.1 `aegle_phr/phr/profile_share.py`

Mirror `uil.py` exactly — module banner explaining the header family and what is unconfirmed, `_headers()`, `_parse()`, `_execute()`, `archive()` on every call, `AbdmResult` returns.

```python
def share_profile(settings, x_token, hip_id, counter_id, patient, request_id=None) -> AbdmResult
def get_token_details(settings, x_token, limit=-1) -> AbdmResult
```

`_execute()` here needs a **GET branch** as well as POST — `get_token_details` is a GET with query params. `subscription.py`'s own `_execute()` already has that GET branch; copy its shape.

`x_token` is a patient session token. Pass it to `archive()` as a `plaintext_secret` so it is scrubbed from `abdm_call_log`, the same discipline `link_confirm()` uses for the OTP. **The token must never reach a log line, a report, or an archived row in the clear.**

### 4.2 `aegle_phr/models.py` — one new model

`ProfileShareRequest`, in the style of `UilLinkRequest`:

```
id              BigInteger PK
request_id      Text unique indexed   (our REQUEST-ID on the share call)
hip_id          Text
counter_id      Text
abha_address    Text
status          Text     PENDING | SHARED | TOKEN_ISSUED | ERROR
token_number    Text null
token_expiry    Text null            (whatever ABDM sends -- Text, see below)
detail          JSONB null           (the share response, then the callback payload)
source          Text null            CALLBACK | POLL -- which mechanism produced the token
created_at / updated_at
```

`token_expiry` is **Text, not an interval or a timestamp**, on purpose: P21 §3.5 records that this field's own semantics are unresolved (`"1800"` in both samples, a stringified `LocalDateTime` on one NHA code path). Store what arrives; let the UI decide how to show it. Put that reasoning in the model's docstring.

### 4.3 `alembic/versions/20260929_0007_<newrev>_create_profile_share_request.py`

`down_revision = "f6a7b8c9d0e1"`. Follow the style of the existing 6.

### 4.4 `aegle_phr/phr/profile_share_repository.py`

Same shape as `uil_repository.py` — plain functions over `session_scope()`, dict in, dict out, no ORM object escapes:

```python
save_new_share(request_id, hip_id, counter_id, abha_address, detail=None) -> None
get_by_request_id(request_id) -> dict | None
update_by_request_id(request_id, status, detail=None, token_number=None, token_expiry=None, source=None) -> dict | None
find_latest_pending(abha_address, counter_id=None) -> dict | None   # Candidate A's fallback correlation
list_recent(abha_address, limit=20) -> list[dict]
```

### 4.5 `aegle_phr/callbacks/profile_share_services.py` + `callbacks/router.py`

New module in the shape of `uil_services.py`: a plain `def`, never raises, `handle_on_share(settings, payload, request_id_header)`.

In `router.py`, add a `_PROFILE_SHARE_HANDLERS` dict — **a separate dict, alongside `_SUBSCRIPTION_HANDLERS` / `_UIL_HANDLERS` / `_HIU_HANDLERS`, not merged into any of them**, matching the per-feature-area convention that module's own comments already state. Add it to the chained lookup in `_make_handler()`.

**Also update `CALLBACK_ROUTES`' own comment.** It currently says `on_share remains archive-only, no chunk has built it yet`. That sentence becomes false in this chunk; leaving it would mislead the next reader. Replace it with what is now true, including that the payload shape is still unproven.

### 4.6 `aegle_phr/phr/schemas.py` + `aegle_phr/api.py` — four routes

Schemas in the existing style (`UilDiscoverBody` etc.): `ScanShareParseBody`, `ScanShareShareBody`, `ScanShareTokenDetailsBody`.

Routes, matching the `/phr/uil/*` four exactly in structure — `_passthrough()`, the `X-Aegle-Key` gate the router already applies, `summary=` strings that name the uncertainty:

```
POST /phr/scan-share/parse
     Body: {"scanned": "<the raw text out of the QR, or a pasted URL>"}
     Returns: {hipId, counterId, facilityName | null, raw}
     Pure local parsing, NO ABDM call. Accepts:
       - a full https://phrsbx.abdm.gov.in/share-profile?hip-id=...&counter-id=... URL
       - any URL carrying hip-id and counter-id query params (do not hardcode the host --
         production's host is unknown, see P21's own config comment)
       - a bare "hip-id=...&counter-id=..." query string
     Rejects with a clear 400 naming what was missing when hip-id is absent.
     counter-id absent is NOT an error -- default it to "" and say so in the response.
     facilityName: look it up through the EXISTING provider directory
     (aegle_phr/phr/providers.py). Best-effort -- a lookup failure returns null and
     must not fail the parse, because the share works without a display name.

POST /phr/scan-share/share
     Body: {xToken, hipId, counterId, patient:{...}}
     Generates our REQUEST-ID, saves the PENDING row BEFORE calling (same ordering as
     the UIL routes, for the same reason -- the callback can arrive before the HTTP
     response does), calls share_profile(), returns the passthrough plus requestId.

GET  /phr/scan-share/result?requestId=...
     Reads our own row. The frontend's async-wait mechanism, same as /phr/uil/result.

POST /phr/scan-share/token-details
     Body: {xToken, limit?}
     Calls ABDM's getTokenDetails. Returns the body VERBATIM -- do not reshape a
     response shape nobody has seen.
```

The `patient` object on `/share`: the **frontend** supplies it, from the profile it already fetched and displayed on the consent screen. Do not re-fetch it server-side. The patient must be shown exactly what will be sent, and the only way to guarantee that is to send what was shown.

### 4.7 `testui/` — the Scan screen

New `testui/src/routes/ScanShareScreen.tsx`, route `/scan`, plus its calls in `src/api/endpoints.ts`. Model it on `UilLinkScreen.tsx` (24 KB — the closest existing screen: async, poll-driven, multi-step) and use the existing `src/components/ui/*` primitives. No new design system.

**Three ways to get the QR in, all three built, in this order of prominence:**

1. **Camera.** `navigator.mediaDevices.getUserMedia` plus a decode-only QR library working over video frames on a canvas. `jsqr` is the intended choice — **verify the exact published package name and its import shape before adding it**, and if it is not what this prompt says, use any equivalent decode-only library and note the substitution. Whatever it is, it is the only new dependency in this chunk. Camera access needs a secure context: it works on `localhost` and on the Vercel https deployment, and **fails on a plain-http LAN address**. Detect that and say so in the UI rather than showing a dead button.
2. **Upload an image.** The same decoder against a `<canvas>` built from a `File`. **This is the one Aayush will actually use first**, because P21's test flow writes the counter QR out as a PNG — so the loop closes with no camera at all. Make it obvious, not buried.
3. **Paste the URL.** A plain text box. Always works, never blocked, and the fallback when the other two fail.

Then the flow on screen:

- After a successful decode: show `hipId`, `counterId`, and the facility name if `/parse` found one.
- **Consent step.** Show the exact fields that will be sent, each labelled, read from the profile the app already holds. A visible "Share these details with <facility>" confirm button. Do not share on decode — the tap is the consent, and this screen is the only place the patient ever sees it.
- After sharing: poll `/phr/scan-share/result` every 2s for up to 60s. While waiting, also call `/phr/scan-share/token-details` — that is Candidate B, and it may be the only thing that ever answers.
- **Success:** the token number, large; the facility name; the expiry as-received (render `"1800"` as "valid ~30 minutes" **only if** the value is all digits, otherwise print it raw — the semantics are unconfirmed and a wrong unit on screen is worse than a raw string).
- **Timeout:** say plainly that the share was accepted but no token came back, show the `requestId`, and say which of the two mechanisms were tried. An honest dead end beats a spinner.
- Every raw request/response goes to the existing `ConsolePanel` / `RawBody` mechanism, same as every other screen.

**Navigation.** Give `/scan` the `raised: true` middle slot in `PRIMARY_NAV` — that slot's own docstring calls it "the reference app's QR-scan treatment", and this is finally the actual QR scan. Consent becomes a flat tab. To stay at five tabs, **move Providers into the `MenuDrawer`** (it is a lookup, not a daily destination). Update `App.tsx`'s comment above `PRIMARY_NAV`, which currently asserts *"nothing in this app is a closer match"* — that is the sentence this chunk invalidates. **Flag this layout change in the report as a reversible product call**, not a technical necessity; Aayush may want something else dropped instead.

---

## 5. Out of scope

Flag, do not fix.

- **Anything in `repo/`.** P21 owns the facility side. If this chunk reveals a bug there, report it.
- The patient's own ABHA QR (`/phr/profile/qr-code`, SS3.40) — a different thing that happens to also be a QR.
- Any change to how consent, subscription, locker or UIL work.
- Production hosts and URLs.

---

## 6. Verification

**V1 — migration round-trips.** `alembic upgrade head`, confirm the table, `downgrade -1`, confirm it is gone, `upgrade head` again. Paste the real `\d profile_share_request` output.

**V2 — both deployments still start.** `aegle-phr` standalone, **and** mounted inside `repo/server/main.py` (the log line `PHR app mounted (aegle_phr).`). §4.5 touches the shared callback router, so a mistake here breaks the backend too.

**V3 — routes.** Print the route table; confirm the four new `/phr/scan-share/*` routes exist, `/api/v3/hiu/patient/on-share` is still registered exactly once, and nothing that existed before has gone.

**V4 — URL parsing, no network.** Feed `/phr/scan-share/parse` at least six inputs: the full sandbox URL; the same with the params reversed; a different host carrying the same params; a bare `hip-id=X&counter-id=Y`; a URL with `hip-id` but no `counter-id` (must succeed, empty counter); junk text (must 400 with a message naming what was missing). Assert each result.

**V5 — the callback handler, no network.** Call `handle_on_share()` directly with **five** payloads: P21's own ack shape wrapped in `{acknowledgement, response:{requestId}}`; the same with no `response` envelope (fallback correlation on abhaAddress+counter must find the row); `{profile:{tokenNumber}}`; `{tokenNumber}`; and a payload with no token anywhere (must not raise, must store raw, must log). Assert the row's `status`, `token_number` and `source` after each.

**V6 — typecheck and build the UI.** `npm run typecheck` and `npm run build` in `testui/`, both clean. Paste the output.

**V7 — decode a real QR image.** Take the PNG that P21's own flow writes (`repo/tools/m2_test_suite/logs/scan_share_qr_*.png`) and prove the upload path decodes it to the right `hip-id` and `counter-id`. Prove it against that real file, not a synthetic one — this is the specific thing Aayush needs in order to test at all. (That flow only writes the PNG when `qrcode[pil]` is installed in the `repo` environment. If it is missing, install it there rather than substituting a QR you generated yourself — the point is to decode the artefact the facility side actually produces.)

**V8 — the joint live test.** This is the payoff, and the only test that proves anything about ABDM. Both halves run in one process behind one ngrok tunnel.

1. Start `repo/server/main.py`; confirm the PHR app mounted and the tunnel is registered as the bridge URL.
2. In `repo`: `python -m tools.m2_test_suite.cli` → `7` → `1` → Aegle Urgent Care (`IN2410002590`) → counter `OPD-1`. Keep the printed URL and the PNG.
3. In a second terminal, same CLI → `7` → `2` to watch the facility's token board.
4. In the test UI: log in as a sandbox patient, open **Scan**, upload that PNG, check the consent screen shows the right facility and the right fields, tap Share.
5. Report, precisely:
   - the HTTP status and body ABDM returned to `/patient-share/v3/share` (**this settles §3.2**)
   - whether `/api/v3/hiu/patient/on-share` fired at all, and if so its **full payload verbatim** (**this settles §3.3 Candidate A** — the single most valuable output of this chunk)
   - what `getTokenDetails` returned, verbatim (**settles Candidate B's shape**)
   - whether the facility's token board showed a token, and whether the PHR screen showed **the same number**
   - which `source` the row ended up with, CALLBACK or POLL

If it fails, say where and stop. Do not claim V8 passed without a real token on both screens. A precise failure is a good result here; a vague success is not.

**V9 — nothing else moved.** `git status` / `git diff --stat` in `aegle-phr`, and confirm `repo/` and `aegle-abdm-core` are untouched. Confirm nothing under `logs/` or `storage/` was deleted or truncated.

---

## 7. Standing ground rules

1. **No git commit, no git push, no git init.** Leave everything as uncommitted working-tree changes.
2. **No throwaway scripts left behind.** Delete anything written only to verify something.
3. **Scope discipline.** Nothing beyond this prompt. Problems found elsewhere get flagged, not fixed. Regressions you cause are yours to fix.
4. **Never delete or truncate anything under `logs/` or `storage/`,** in either repo, for any reason.
5. **Never print a secret.** The patient's `X-AUTH-TOKEN` above all — it must be scrubbed from `abdm_call_log`, absent from every log line, and absent from your report. Also the gateway token and `CLIENT_SECRET`.
6. **`Authorization: Bearer <token>`**, never an `apikey` header.
7. **Testing must not change real output data.** Back up, test, restore.
8. **Flag uncertainty visibly.** Every item in §3.2 and §3.3 gets an explicit `UNCONFIRMED:` marker in the code and a line in the report. Do not present a guess as fact.
9. **`aegle-phr` must not modify `repo/`.** It may read from it at runtime; it may not change it.

---

## 8. Report back

**Part 1 — detailed change report.** Per file: what changed, where, why. Every `UNCONFIRMED:` marker listed with the contradiction or silence behind it. Say explicitly which decisions came from `uil.py`'s live-proven precedent rather than from documentation.

**Part 2 — a concise summary to paste into Cowork.** It must answer:

- files added / modified, in both `aegle_phr/` and `testui/`
- V1–V9 individually, with the actual outcome — never the word "passed" on its own
- **the three unknowns from V8**: the `/share` response, the `on-share` callback payload (or its absence), and the `getTokenDetails` shape — verbatim, redacted of tokens
- whether the same token number appeared on both screens
- the layout call from §4.7, so Aayush can overrule it
- everything flagged-not-fixed
- exact steps to re-run the joint test from a cold start
