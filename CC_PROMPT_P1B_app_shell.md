# Claude Code prompt — P1-B: real navigation (login page + routing shell)

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet, extended thinking on.**

---

Restructure `testui/` from one flat page into a real app shell with actual routes. **This chunk is
frontend-only — zero backend changes, zero new ABDM calls, zero OTP risk.** It exists so the
registration paths and login methods still to come attach to real routes instead of piling onto one
page the way `Register` currently does.

## Why now, and why scoped this tightly

Right now there are two screens sharing one page: `Health` and the mobile `Register` stepper. This
is the cheapest point to introduce routing — before more screens exist to migrate. Deliberately
**not** bundled with the password-login flow that comes next: this chunk changes navigation
structure, that one will change backend behavior, and mixing "restructure how screens are reached"
with "build a new authenticated flow" in one diff makes both harder to review. Do only the shell here.

## What to build

1. **Add client-side routing** (React Router). Real URLs, working browser back/forward — not a
   `useState` page switch.

2. **Routes:**
   - `/login` — the new landing page. Default route; `/` redirects here.
   - `/enroll` — the existing mobile-registration stepper, moved here **unchanged in behavior**.
     Same component, same logic, same calls through `client.ts` — only its location in the app
     changes, from always-visible to reached by navigation.
   - `/health` — the existing Health screen, moved here unchanged.

3. **The `/login` page:**
   - Three method options — **Mobile**, **ABHA Number**, **Aadhaar** — each its own real route
     (`/login/mobile`, `/login/abha-number`, `/login/aadhaar`). None of their backends exist yet,
     so each renders a plain, honestly-labeled "Not built yet" screen. This is not a placeholder for
     a flow we're pretending exists — it's a real route that truthfully says the flow isn't wired up.
     No fake success state, no spinner that goes nowhere.
   - A clearly separate **"Don't have an ABHA? Enroll"** link/button, routing to `/enroll`.
   - Nothing here talks to the backend. This page is pure navigation.

4. **Don't build a post-login Home/Dashboard stub in this chunk.** Nothing produces a session yet,
   so a destination for one has no real content to hold. Add it alongside the first flow that
   actually needs it (next chunk).

5. **Update `testui/README.md`'s "add a screen" recipe** to an "add a route" recipe reflecting the
   router — this is what makes every future chunk drop-in.

6. **Everything else stays exactly as it is:**
   - No component library, plain CSS, one file.
   - `fetch()` still appears nowhere outside `client.ts` — routing touches zero networking code.
   - The Console panel, connection-status indicator, and settings panel are unchanged and still
     reachable (decide where they live in the new layout — e.g. a persistent header/footer across
     routes — and say what you chose).
   - The `?api=…&key=…` link-then-strip behavior on first load is unaffected by routing; verify it
     still works with the router in place (this is the one place routing and existing behavior
     genuinely interact — the `history.replaceState` call that strips the query params must not
     fight with the router's own history management).

## Explicitly out of scope — flag, don't build

- Any of the three login methods' actual backends.
- Password login (the very next chunk — it reuses the RSA/certificate/archive plumbing already
  proven in P1-A, and unlike OTP paths it can be tested repeatedly with no SMS/lockout risk, so
  it's the natural first thing this shell gets wired up to).
- Session/token storage design for a logged-in state. Note in your report where you'd put it
  (the enrol response already returned `tokens.token`/`refreshToken`, which carry PII in their
  claims) but do not implement anything — that's a real decision for the next chunk, not this one.
- Any change to `aegle_phr/` (the Python backend), `repo/`, or `aegle-abdm-core/`. This chunk is
  `testui/` only.

## Verification

1. `npm install`, `npm run build`, strict `tsc --noEmit` — zero errors, zero warnings.
2. `grep`: `fetch(` still only in `client.ts`.
3. Manual click-through, reported step by step:
   - Loading the bare URL lands on `/login`.
   - Each of the three method buttons navigates to its own URL and shows the honest "not built yet"
     state — not a silent no-op, not a fake success.
   - "Enroll" reaches the real stepper and it still functions exactly as it did before this chunk
     (drive it through at least the request-OTP step against the running backend to confirm nothing
     broke — no need to complete a full registration, just confirm the screen renders and the first
     call fires correctly).
   - Browser back/forward move between routes sensibly.
   - Opening a link with `?api=…&key=…` still saves to `localStorage` and strips the query params,
     with the router in place.
4. Confirm `/health` still works, reached via its new route.

Delete verification scripts once they pass.

---

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline — routing and the `/login` shell only. Flag anything else you spot,
   don't fix it. Fix bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — especially the session-storage design note in "Explicitly out of scope".
8. Do not modify `aegle_phr/`, `repo\`, or `aegle-abdm-core\`. `testui/` only.
9. Never print the access key or client secret into your report.
