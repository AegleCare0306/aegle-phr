# Claude Code prompt — P1-E: all remaining PHR login methods

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

Wire every PHR login method the spec documents that isn't built yet. Mobile OTP (§3.11-3.12) and
password (§3.23-3.25) are done. This chunk covers the remaining **five** documented method-pairs —
§3.13 through §3.22 — in one chunk, per Aayush's explicit instruction to build them together rather
than one at a time. **There is no sixth method to look for**: face-verify appears only as diagrams
in this spec, with no API section — already confirmed absent, don't go looking for it again.

## The five flows — all share the same two endpoints as mobile login

Every one of these uses `POST /phr/app/login/request/otp` then `POST /phr/app/login/verify` — same
URLs already wired for mobile login, just different `scope`/`loginHint`/`otpSystem`/`loginId`. Then
every one of them finishes with the **already-built, unmodified** `verify_user()` — the `T-token`
fix from the last chunk applies here too, with zero changes needed to that function.

### 1. ABHA Number, via Aadhaar OTP — §3.13-3.14
`request/otp`: `scope: ["abha-login","aadhaar-verify"]`, `loginHint: "abha-number"`,
`loginId: <encrypted ABHA number>`, `otpSystem: "aadhaar"`. OTP goes to the Aadhaar-registered
mobile, not whatever mobile is on the ABHA profile. `verify`: same scope, standard
`authData.otp.{txnId,otpValue}` shape, response UNDOCUMENTED (blank in spec, same gap pattern as
every `verify` so far).

### 2. Raw Aadhaar Number, via Aadhaar OTP — §3.15-3.16
`request/otp`: `scope: ["abha-login","aadhaar-verify","aadhaar-otp-verify"]` — **three scopes**, not
two, the only flow in this batch with that shape. `loginHint: "Aadhaar-number"` (capital A in the
spec's own example — copy it exactly, ABDM scope/hint strings have been case- and value-sensitive
every time this project has tested them). `loginId: <encrypted Aadhaar number>`,
`otpSystem: "aadhaar"`.

**This is the one flow in the batch with a real documented `verify` success body** — use it as a
starting reference, not gospel (every other "documented" response in this project has had at least
one surprise once actually called):
```json
{ "txnId": "...", "message": "OTP verified successfully", "authResult": "success",
  "users": [ {"abhaAddress": "...", "fullName": "...", "abhaNumber": "...",
              "status": "ACTIVE", "kycStatus": "VERIFIED"} ],
  "preferredAbhaAddress": "kiranbornare5467@sbx",
  "tokens": { "token": "{{encrypted-T-token}}", "expiresIn": 300, "switchProfileEnabled": false } }
```
Two things worth noting explicitly in your report: (1) `preferredAbhaAddress` is a field not seen in
any `verify` response captured so far — if it's genuinely present live, it's a reasonable default
selection in the address-picker UI, but don't build UI behavior around it beyond "pre-select it if
present" since nothing documents what picking a different one does differently. (2) the spec's own
placeholder value for the transfer token is literally `"{{encrypted-T-token}}"` — that's the spec
itself naming the field "T-token" a section away from where the last chunk had to discover the same
name live, undocumented. Worth a line in the README noting the spec *did* name it, just not where
anyone would look for it while implementing `verify/user`.

### 3. ABHA Number, via Mobile OTP — §3.17-3.18
`request/otp`: `scope: ["abha-login","mobile-verify"]`, `loginHint: "abha-number"`,
`loginId: <encrypted ABHA number>`, `otpSystem: "abdm"`. OTP goes to whatever mobile is linked to
that ABHA number. `verify`: same scope, standard shape, response UNDOCUMENTED.

Spec has a business-rule note here worth recording but not implementing anything special for: *"For
users logging in with a KYC verified ABHA address, only KYC verified addresses should be displayed;
for a mix, both KYC verified and pending should be displayed."* This describes ABDM's own
server-side filtering of `users[]` — nothing for our client to do about it, just don't be surprised
if `users[]` is filtered differently across flows.

### 4. ABHA Address, via Mobile OTP — §3.19-3.20
`request/otp`: `scope: ["abha-address-login","mobile-verify"]`, `loginHint: "abha-address"`,
`loginId: <encrypted ABHA address>`, `otpSystem: "abdm"`. `verify`: same scope, standard shape,
response UNDOCUMENTED. Spec note: *"When logging in with an ABHA address, the Switch Profile option
should not be displayed"* — expect `tokens.switchProfileEnabled: false` here; don't hardcode hiding
a UI element based on this, just don't be surprised by the value.

### 5. ABHA Address, via Email OTP (marked "Optional" in the spec) — §3.21-3.22
Spec's own note: *"This login functionality is available for the integrator, not for the ABHA
app."* We're the integrator (Aegle is a third-party PHR app, not the official ABHA app), so this
applies to us — build it like the other four, not skipped.

**Flag this discrepancy rather than resolving it yourself**: the section's prose says *"the login
hint should be the ABHA address,"* but its own request-body example shows `loginHint: "email"` with
`loginId: <encrypted email>` — the identifier being submitted is the email address itself, not the
ABHA address, contradicting the section's own description one sentence earlier. Build against the
example body (`loginHint: "email"`, encrypted email as `loginId`) since a JSON example is more
concrete than prose, but **test this live and report which one ABDM actually accepts** rather than
assuming the example is right — this is exactly the kind of spec self-contradiction this project has
hit before (P1-C's `verify` shape, the T-token gap), and the fix each time was to trust the live
sandbox over any single part of the doc.

## Design suggestion, not a mandate: don't hand-copy five near-identical functions

`request_mobile_otp()`/`verify_mobile_otp()` in `login.py` already have this exact shape (encrypt
loginId, POST, parse). All five new flows differ only in `scope`, `loginHint`, `otpSystem`, and what
gets encrypted into `loginId` — the `verify` call bodies differ only in `scope`. A shared
`request_otp(scope, login_hint, login_id, otp_system)` / `verify_otp(scope, txn_id, otp)` pair that
every method (including the existing mobile one, if you want to fold it in) calls with its own
constants is probably cleaner than five copy-pasted near-duplicates — but this is your call to make
based on what the code actually looks like once you're in it, not a requirement. State what you
chose and why.

## Reuse — nothing else changes

- Encryption, `abdm_call_log` archiving, retry policy (no retry on OTP request, same as every prior
  OTP flow) — identical to mobile login.
- `verify_user()` — **completely unchanged**, already takes `t_token` and requires it.
- Session storage (`session.ts`, `sessionStorage` for `token`, `refreshToken` never persisted) —
  unchanged, no new design decision needed.
- Redaction — check each new flow's actual response for undocumented plaintext fields the way P1-C
  and P1-D both had to (P1-C found `mobile` leaking on `search`; that class of surprise should be
  assumed possible on every new endpoint until proven otherwise, not assumed fixed globally). Aadhaar
  numbers in particular: treat a raw or partially-masked Aadhaar number in any response the same way
  `mobile` and `password` are already treated — plaintext-unsafe, redact if found.

## UI

The `/login` page (P1-B) currently has four top-level options — Mobile, ABHA Number, Aadhaar,
Password — plus Enroll. That mapping was made before this project had visibility into how many
distinct methods the spec actually has per identifier type. It doesn't split evenly:

- **ABHA Number** → now two sub-methods (Aadhaar OTP §3.13-14, Mobile OTP §3.17-18). Needs a choice
  between them after entering the ABHA number, or two distinct entry points — your call, keep it
  simple.
- **Aadhaar** → one method (§3.15-16, raw Aadhaar number + Aadhaar OTP). Maps directly, no change.
- **Two flows have no existing button at all**: ABHA Address + Mobile OTP (§3.19-20) and ABHA
  Address + Email OTP (§3.21-22). Both are keyed by ABHA address, not by any of the four existing
  categories. Add whatever entry point makes sense (e.g., a fifth top-level option, or a sub-choice
  reached from somewhere sensible) — **state clearly in your report what you chose and why**, this
  is a real navigation decision Aayush should see plainly, not one to bury in a diff.

Every screen: reuse the picker-then-`verify_user` pattern already built for mobile login
(`MobileLoginScreen.tsx`) rather than inventing a new shape per method. Aadhaar-number and
ABHA-number inputs should get the same "never persisted, masked like a password" treatment already
applied to OTPs and passwords, since they're personally identifying, even though the field itself
isn't literally a secret. Follow the P1-B "adding a route" recipe.

---

## Verification

**Offline first, for all five flows together:**
1. Every `request/otp` body matches its section's exact `scope`/`loginHint`/`loginId`/`otpSystem` —
   field by field, including the three-scope case for raw-Aadhaar login.
2. Every `verify` call reuses the already-fixed `verify_user()` correctly — `t_token` threaded
   through from each flow's own `verify` response the same way mobile login already does it.
3. Redaction: assert (not just inspect) that no new plaintext PII appears in `abdm_call_log` across
   all five flows' captured responses, extending `extra_response_secrets` wherever needed.
4. `sessionStorage`/`localStorage` split still holds after adding five new screens.
5. All new routes 401 without `X-Aegle-Key`.
6. `tsc --noEmit` and `npm run build` clean; `fetch(` still only in `client.ts`.

**Then live, one flow at a time — this is the part that costs real OTPs, don't blitz through it:**
7. For each of the five flows, stop and ask me for the identifier (ABHA number / Aadhaar number /
   ABHA address / email as applicable) and to read back the OTP — same one-shot rule as every prior
   live run: request once, verify once per flow, don't loop. Do **not** queue up all five OTP
   requests before checking in — walk one flow fully (request → verify → pick address → verify-user)
   before starting the next, so a failure on flow 2 doesn't burn OTPs on flows 3-5 chasing the same
   mistake.
8. For each flow, capture and report the actual `verify` response body (redacting token/PII values,
   describing presence/shape) into `aegle-phr/README.md`'s captured-shapes section — same
   documentation deliverable as every prior chunk. Explicitly resolve the email-vs-ABHA-address
   `loginHint` question for flow 5 with the real result, not the example body's assumption.

If any flow's live run fails, stop and report that flow specifically — don't let one failure stop
you from reporting what the other flows already confirmed; don't re-request an OTP for a failed flow
without asking first.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — these five login methods only. Flag anything else you spot, don't fix
   it. Fix bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially the email/ABHA-address `loginHint` contradiction in flow 5,
   and whatever navigation structure you chose for the two flows with no existing button.
8. Do not modify `repo\` or `aegle-abdm-core\`.
9. Never print the access key, the client secret, a plaintext OTP, an Aadhaar number, a mobile
   number, an email address, or a live token into your report.
