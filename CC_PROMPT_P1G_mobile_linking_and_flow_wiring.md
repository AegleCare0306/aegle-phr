# Claude Code prompt — P1-G: mobile linking (skip when redundant) + wire the enrollment sequence together

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

> This assumes P1-F already ran (it has — `aegle_phr/phr/aadhaar_enrollment.py`,
> `aegle_phr/phr/email_verification.py`, `AadhaarRegisterScreen.tsx`, `SetPasswordScreen.tsx` all
> exist and were read directly before writing this prompt). This chunk builds on that code, it does
> not redo it.

---

## Aayush's mental model for this app — read this before touching anything

There are three distinct entry points into this app, not one:

1. **Login** — an existing ABHA account, multiple OTP methods. Separate topic, currently its own
   investigation, not this chunk.
2. **Enroll for the first time** — no ABHA account yet. Aadhaar OTP creates the ABHA Number and
   profile, then **mobile linking, then email linking, then ABHA address suggestion and creation**
   finish the account. **This chunk is entirely about finishing this flow correctly.**
3. **Already have an ABHA account, want an additional ABHA address** — a different entry point
   (verify ownership via ABHA-Number+Aadhaar-OTP or ABHA-Number+Mobile-OTP, §3.4-§3.10 of the PHR
   spec, then suggestion/creation same as above). **Not this chunk — flagged at the end, not built.**

**The standing rule for all of this, stated directly by Aayush:** if the app already has a piece of
data — from an earlier step's response in the same flow, or from what the user already typed a
moment ago — **auto-populate it and never ask again**, unless Aayush explicitly says to ask again.
The concrete example he gave: registration step 1 collects both an Aadhaar number and a mobile
number together. If that mobile turns out to be the same one Aadhaar's own OTP already proved
ownership of, **the mobile-linking step should be skipped entirely** — asking the user to verify a
number ABDM already just verified is exactly the kind of redundant re-ask this rule exists to kill.

## What's already built — read the real files, not this summary, before changing them

- `aegle_phr/phr/aadhaar_enrollment.py` + `AadhaarRegisterScreen.tsx`: step 1 collects Aadhaar number
  + mobile together, step 2 submits the OTP, `enrol/byAadhaar` returns `ABHAProfile` (full
  demographics, including a **masked** Aadhaar-linked mobile, e.g. `"******0903"`) and — per Aayush's
  own saved Postman example, not yet independently confirmed live — possibly a full session token
  directly.
- `aegle_phr/phr/email_verification.py` + the "Link an email address (optional)" fieldset in
  `AadhaarRegisterScreen.tsx`: already does the right thing for email — asks once, never had the data
  before, sends a real verification link. **Nothing to fix here except where it sits in the
  sequence** (see Change 3).
- `SetPasswordScreen.tsx` (`enrol-from-aadhaar` + `suggestions-from-aadhaar`): already auto-populates
  every demographic field from `ABHAProfile` — this part of the auto-populate rule is already done
  correctly, confirmed by reading the file directly. Only `password` and the ABHA address are real
  form inputs.
- **What does NOT exist anywhere**: a "mobile linking" step. The mobile typed in step 1 is used
  as-is, forwarded through `aadhaarRegistrationBridge.ts`, and never independently verified or
  compared against anything. There is no skip logic because there is no step to skip — this is a
  real gap, not a redundant-but-present step.
- **A real wiring gap that blocks reaching the fix**: `AadhaarRegisterScreen.tsx`'s "logged in"
  branch (where the email-link fieldset lives) only renders when `getSessionToken()` returns
  non-empty. That only happens if `enrol/byAadhaar` itself returned a full session token *or* the
  user clicks "Use this session" on that same screen. `SetPasswordScreen.tsx`'s own submit handler
  **never calls `setSession()`** at all — its comment literally says "whether this response carries
  a patient session token is not documented." If a tester's account needed the password step (no
  direct session from `enrol/byAadhaar`), there is currently no path back to a logged-in state at
  all, which means no path to email-linking today, and would mean no path to the new mobile-linking
  step either. Fix this as part of this chunk (Change 2) — otherwise Change 1 builds a step nobody
  can reliably reach.

## Change 1 — the mobile-linking step, with the skip-when-redundant rule

**New ABDM calls, straight from the PHR spec (§3.26-§3.27) — not from `repo/`, this one isn't in the
M1 reference:**

- `POST /abha/api/v3/phr/app/login/profile/request/otp`, body
  `{scope: ["abha-address-profile","mobile-verify"], loginHint: "mobile-number", loginId: <encrypted
  mobile>, otpSystem: "abdm"}` → `{txnId, message}`.
- `POST /abha/api/v3/phr/app/login/profile/verify`, body `{scope: ["abha-address-profile",
  "mobile-verify"], authData: {authMethods: ["otp"], otp: {txnId, otpValue: <encrypted OTP>}}}` →
  documented success: `{txnId, message: "Mobile Number linked successfully", authResult: "success",
  users: [{abhaAddress}]}`.

**Certificate — get this right, don't default to what the last chunk used.** Every other
`/phr/app/login/*` endpoint already built in this project (mobile OTP login, all five P1-E methods)
encrypts against `settings.phr_certificate_url` (2048-bit, `/phr/app/login/public/certificate`) — and
this endpoint lives under that exact same URL family (`/phr/app/login/profile/...`), not under
`/enrollment/...` or `/profile/...` (ABDM-core). **Use `phr_certificate_url` here, not
`abdm_profile_certificate_url`.** The last two chunks' endpoints (`aadhaar_enrollment.py`,
`email_verification.py`) both correctly use the profile cert because they hit genuinely different
ABDM URL families (`/enrollment/...`, `/profile/account/...`) — don't copy that choice reflexively
just because it was the most recent pattern; the URL family is what decides the certificate, and this
one matches the PHR-native family already using `phr_certificate_url` everywhere else.

**X-token — very likely required, confirm rather than guess-and-retry live.** The spec's own header
table for §3.26/§3.27 lists only `Authorization`/`REQUEST-ID`/`TIMESTAMP`, the same incomplete
pattern already found twice in this project (`verify/user`'s missing `T-token`, §3.30's own error
table a few lines later literally has a `"When passing without T token"` 403 scenario for a
neighboring Profile endpoint). Every endpoint in this spec under the `abha-address-profile` scope
family is a **post-login** action — update email, update password, link/delink ABHA number all sit
right next to this one and all clearly require an authenticated session. **Send both `Authorization`
(gateway token) and `X-token` (the session token from step 1's grant) on the first live attempt** —
don't burn an OTP finding out the header table was incomplete a third time when the pattern is
already this strong; only fall back to testing without `X-token` if including it still fails.

**The skip logic — the actual point of this chunk:**

1. After Aadhaar registration succeeds, `ABHAProfile.mobile` comes back **masked**
   (`"******0903"` per the confirmed example) — compare its last 4 digits against the last 4 digits
   of the mobile the user typed in step 1 (already held in `aadhaarRegistrationBridge.ts`'s
   `mobile` field — full plaintext, since it's what the user typed).
2. **If they match**: do not call either new endpoint. Show something like "Mobile number already
   verified via Aadhaar OTP — no separate verification needed" and treat this step as complete.
3. **If they differ, or `ABHAProfile.mobile` is missing/unparseable**: show the linking step for
   real — pre-fill the mobile field with what the user already typed (editable, in case they want to
   link a third number instead — Aayush's rule is "don't re-ask what we already have," not "never let
   them change their mind"), request OTP, verify OTP, same one-shot pattern as every other OTP step
   in this project.
4. State plainly in your report which comparison method you used (last-4-digit match is the
   suggestion here, since that's all a masked value gives you) and whether the live `ABHAProfile.mobile`
   value actually came back masked the way the confirmed example showed, or differently.

**Where this lives**: new module `aegle_phr/phr/mobile_linking.py`, mirroring
`email_verification.py`'s shape (small, two functions, `AbdmResult` dataclass, `archive()` +
redaction the same way). New routes, e.g. `/phr/profile/link-mobile/request-otp` and
`/phr/profile/link-mobile/verify-otp`, gated the same way every other app-API route is
(`X-Aegle-Key`). New schemas in `schemas.py` following the existing naming conventions.

**Redaction**: the mobile number (both the one being linked and whatever comes back in
`users`/response bodies) gets the same plaintext-secret treatment already given to every other
mobile number in this project — assert it, don't just inspect it, same proof technique as every
prior chunk (`redaction.contains_any()`).

## Change 2 — fix the session-wiring gap so the new step is actually reachable

`SetPasswordScreen.tsx`'s submit handler needs the same `extractSessionToken()`-style check
`AadhaarRegisterScreen.tsx` already has (copy or share the helper — your call which, state which you
picked). If `enrol-from-aadhaar`'s response carries a full session token (test this live — the
module's own docstring already flags this as unconfirmed), call `setSession()` before navigating, so
a tester who needed the password step still ends up logged in and can reach mobile-linking and
email-linking afterward. **If it genuinely never carries a session** (confirm live, don't assume):
say so plainly, and make the post-password-set screen point the tester at an already-working login
method (mobile OTP) to reach the linking steps instead — whichever of these two is actually true,
this chunk should not leave a dead end where the linking steps exist in code but nothing routes a
password-path tester to them.

## Change 3 — sequence mobile-linking and email-linking together

Aayush described these as one sequential process: mobile linking, then email linking, then address
suggestion/creation. Right now the (already-working) email-link fieldset sits alone in the
"logged in" branch of `AadhaarRegisterScreen.tsx`. Add the new mobile-linking step to the same
branch, **ahead of** the email fieldset (mobile first, matching the order Aayush described), so a
tester who lands there sees them as one obvious sequence rather than two disconnected optional
add-ons. Keep both genuinely skippable/optional in the UI the way email already is — Aayush's rule is
about not re-asking known data, not about forcing every step to be mandatory before moving on;
state plainly if you think one of them should be mandatory instead and why, but don't make that call
unilaterally.

## Explicitly out of scope — flag, don't build

Scenario 3 from Aayush's own description ("already have an ABHA account, want to create a new/
additional ABHA address") is a **different entry point** — verifying via an existing ABHA Number
(§3.4-§3.7) rather than raw Aadhaar, then the same suggestion/isExists/enrol chain (§3.8-§3.10) this
project already has working pieces of. **Do not build this now.** Note in your report that it exists
as a known next chunk, and note anything you notice while working on Changes 1-3 that would make that
future chunk easier or harder (e.g. whether `enrollment.py`'s existing `address_suggestions()`/
`address_exists()`/`enrol()` are already generic enough to reuse for it) — but do not start building
it.

---

## Standing rule to check your own work against before calling this done

**Never ask for a piece of data this flow already has** — from an earlier step's response in the
same flow, or from what the user already typed a moment earlier — unless Aayush explicitly said to
ask again. Before reporting this chunk done, re-scan `AadhaarRegisterScreen.tsx`, `SetPasswordScreen.tsx`,
and whatever new screen/fieldset you add against this rule specifically, and report anywhere you
found (or fixed) a violation — not just the mobile-linking gap already known going in. If you find
nothing else, say that plainly rather than leaving it unaddressed.

---

## Verification

**Offline first:**
1. Both new request bodies match §3.26/§3.27 exactly — scope, loginHint, loginId, otpSystem, authData
   shape.
2. Certificate: assert (not just inspect) that the new module calls `get_public_certificate()` with
   `phr_certificate_url`, not `abdm_profile_certificate_url` — this is the specific mistake the
   "Certificate" section above exists to prevent.
3. The last-4-digit comparison logic is unit-testable without a live call — write a small offline
   check (delete once it passes, per the usual rule) confirming match/no-match/unparseable-mask cases
   behave as described.
4. Redaction: assert no plaintext mobile number ends up in `abdm_call_log` for the new endpoints.
5. `tsc --noEmit` and `npm run build` clean; `fetch(` still only in `client.ts`.
6. New routes 401 without `X-Aegle-Key`.

**Then live — this costs at minimum the Aadhaar OTP registration already needs, possibly one more:**
7. Run a full registration where the typed mobile **matches** the Aadhaar-linked one (check the
   masked value in the real response first, then type the same number) — confirm the skip actually
   happens and neither new endpoint gets called. This costs no extra OTP beyond what registration
   already needs.
8. **Stop and ask Aayush before running the mismatch case** — it costs one additional real mobile
   OTP. Once approved: register with a *different* typed mobile, confirm the linking step appears,
   request its OTP, verify it, confirm the `X-token` inclusion works as expected (or report exactly
   what failed if it doesn't).
9. Confirm Change 2's session-wiring fix live: go through the password-setting path at least once
   and confirm the tester ends up logged in afterward (or confirms explicitly that no session is
   ever granted this way, per whichever turns out true).
10. Add whatever this run reveals to `aegle-phr/README.md`'s captured-shapes section, same
    documentation deliverable as every prior chunk — including P1-F's own capture, which doesn't
    exist there yet even though the code is built; backfill P1-F's real captured response shape here
    too if you have it from step 7's registration run, since the README currently stops at P1-D.

If any live step fails, stop and report — don't retry blindly, don't burn a second OTP chasing the
same failure without checking in first.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — Changes 1-3 only, plus the README backfill in verification step 10.
   Flag scenario 3 (new address for an existing account) rather than building it. Fix bugs you
   introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially whether `X-token` turns out required, and whatever the
   self-audit in "Standing rule to check your own work against" turns up.
8. Do not modify `repo\`. `aegle-abdm-core\` may be touched only if genuinely shared logic belongs
   there — this chunk's new calls are PHR-spec-specific (unlike P1-F's Aadhaar/email work, which was
   M1-shared), so the default expectation is everything new lives in `aegle-phr`, not `aegle-abdm-core`.
   State plainly if you conclude otherwise.
9. Never print the access key, the client secret, a plaintext OTP, a mobile number, an email address,
   or a live token into your report.
10. `Authorization: Bearer <gateway token>` everywhere, plus `X-token` where this chunk determines
    it's required — no `apikey` header, consistent with every prior chunk's decision.
