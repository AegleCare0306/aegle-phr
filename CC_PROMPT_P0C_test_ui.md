# Claude Code prompt — P0-C: test UI, one shared key, reachable via the existing ngrok host

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\`.
> **Recommended model: Sonnet, extended thinking on.**
> **This replaces both earlier P0-C prompts.**

---

Build the **test frontend** for the PHR app, plus the two small backend changes that make it usable by a couple of testers with **zero local setup**.

## The goal, stated plainly

Two or three known testers get **one link**. They open it and start driving ABDM sandbox flows. They install nothing, run nothing, host nothing.

This is a temporary throwaway harness against the ABDM **sandbox** — not a product. Optimise for "it just works from a link", not for defence in depth. The one security measure that stays is a single shared key, for one reason given below.

Three parts, all needed for that link to work.

---

# Part 1 — the smallest useful gate (~15 lines)

The backend will be publicly reachable through the ngrok host. From P1 onward it can send OTPs to whatever mobile number a caller supplies, using real ABDM sandbox credentials. Left fully open, a scanner hitting the ngrok domain can burn the sandbox rate limits attributed to our ABDM client (`ABDM-1027` locks it for 24 hours). One shared header is enough to stop that, and it costs a tester one paste.

Keep it to exactly this:

- Header `X-Aegle-Key`, checked with `secrets.compare_digest`.
- New setting `phr_api_access_key` from `.env`; placeholder in `.env.example`.
- Empty or unset key → **reject** app-API requests. Fail closed, never fall open.
- Wrong or missing key → **401**, short JSON body. Never echo the key into a response or a log.

**The only structural requirement — and it is not optional:** the dependency goes on the **app-API router only**, never the ABDM callback router. ABDM cannot send our key; if the gate reaches `/api/v3/hiu/*`, every callback fails and it fails *silently from our side*, because ABDM simply stops receiving acks. Attach it at router level on the app router so a new route inherits it by construction.

Skip the ceremony from my earlier draft — no assertable constants, no banner comments. A short comment saying why callbacks are ungated is enough.

**CORS: set `allow_origins=["*"]`, `allow_credentials=False`.** The key is the control, not CORS, and a wildcard means Vercel preview deployments work without editing `.env`. Leave a one-line comment saying this is deliberate for a sandbox harness and should narrow before anything real.

---

# Part 2 — make the backend reachable through the existing ngrok host

Right now the ngrok static domain points at port **8000** (the existing ABDM backend) and the PHR runs on **8001**, so a deployed UI cannot reach it. One ngrok host is a fixed constraint.

Fix it by mounting the PHR router into the existing app. This is what the mountable design in P0-B was for.

In `C:\Users\hp\Desktop\Aayush\repo\server\main.py`, and **nowhere else in that repo**:

```python
try:
    from aegle_phr.bootstrap import bootstrap as phr_bootstrap
    from aegle_phr.api import build_router as phr_build_router
    from aegle_phr.settings import load_settings as phr_load_settings
except ImportError:
    phr_bootstrap = None
```

…then, if the import succeeded, bootstrap and `app.include_router(...)`. If it failed, log one clear line and carry on.

**The try/except is required, not stylistic.** Without it, `repo/` stops booting on any machine that hasn't installed `aegle-phr` and `abdm-core` — turning a standalone, sandbox-tested backend into one with two new hard dependencies. It must still run alone.

Add CORS middleware to that app too, since the UI now calls it there.

**Constraints on this part:**

- `server/main.py` is the **only** file you may touch in `repo\`. Nothing else, for any reason.
- Do not refactor `repo/` onto `abdm_core`. That is a separate later task. Two copies of the session/certificate logic will run in one process — that is expected and fine for now.
- Flag, don't fix: this means **two independent gateway-token caches** in one process, so two `/sessions` calls. There is a known open issue about concurrent requests under the same sandbox `clientId` returning 401. Worth watching; not in scope.
- Verify `repo\` still starts **with `aegle_phr` importable** and, by temporarily shadowing the import, **without it**. Restore anything you shadowed.

---

# Part 3 — the test UI

Lives at `aegle-phr\testui\`. Vite + React + TypeScript (strict).

## The link is the whole UX — this is the part that matters most

The app reads **both** the backend URL and the access key from **query parameters** on first load:

```
https://<app>.vercel.app/?api=https://<ngrok-host>&key=<shared-key>
```

On load: if `api` or `key` are present, save them to `localStorage`, then **strip them from the address bar** with `history.replaceState` so a screenshot or a shared tab doesn't leak the key. On later visits the stored values are used and the plain URL works.

A settings panel lets either value be viewed and edited by hand (key as a password field), for when the ngrok host changes — but **the normal path is: receive link, click, working.** No typing, no fields to hunt for, nothing to install.

## One choke point for every HTTP call

Every request goes through a single `src/api/client.ts`, which attaches `X-Aegle-Key` and records per call:

`id · startedAt · durationMs · method · full URL · request headers · request body · status · response headers · response body · error`

…into an in-memory store rendered by a **Console** panel: newest first, expandable entries, pretty-printed JSON, copy-to-clipboard per entry. Show the key as `••••` in that panel — the console gets screenshotted.

**Hard rule: `fetch()` appears nowhere except `client.ts`.** Every screen from P1 onward then gets full request/response visibility for free. That is the entire reason this harness exists.

Console state is **in memory only** — bodies will contain OTPs and tokens, so nothing goes to `localStorage` except the URL and the key.

## Everything else, kept deliberately small

- Status indicator with three distinguishable states: **unreachable** (network/CORS), **unauthorized** (401), **reachable** (200 plus the `database` flag). A tester with a stale key must see *that*, not a generic failure.
- One working screen: **Health**, calling `GET /phr/health`.
- The UI calls the PHR backend and nothing else — no ABDM URLs, no client id, no client secret, no crypto in the browser.
- **No component library.** Plain CSS, one file. No Tailwind, no MUI, no shadcn. Legible over attractive: readable sans, monospace console, obvious status colours, works at 1280px.
- One muted line in the footer noting this is a sandbox test harness. Not a banner.
- **No placeholder screens** for flows that don't exist yet. P1 adds real ones.
- A `testui/README.md` section showing exactly how to add a screen, so P1 is drop-in.

**The key must never be baked into the build.** No `VITE_*` default, no value in source. Anything in a Vercel bundle is public.

## Vercel

Add `vercel.json` only if genuinely needed. Document in `testui/README.md`: Root Directory must be `testui`, and the shape of the link to send testers.

**Do not deploy and do not run `git init`.** Both are mine.

State plainly in the README that the ngrok tunnel and the backend must be running on my machine for testers to get anything — that is inherent, not a bug.

---

# Verification

Show real output, not claims.

1. `GET /phr/health` — no key → 401; wrong key → 401; right key → 200.
2. `POST /api/v3/hiu/patient/care-context/on-discover` with **no** `X-Aegle-Key` behaves exactly as before (401 from JWT verification; 200 with verification bypassed). **This proves the gate did not leak onto the ABDM surface — the check most worth getting right.**
3. Empty `phr_api_access_key` → app-API requests rejected. Prove it fails closed.
4. `repo\` boots with `aegle_phr` importable, and still boots without it. Show both.
5. With `repo\` running on 8000, `GET http://localhost:8000/phr/health` returns 200 with the key — the mounted route works in the host app.
6. `npm install`, `npm run build`, strict `tsc --noEmit` — zero errors, zero warnings.
7. `grep`: `fetch(` only in `client.ts`; no ABDM URL, client id or client secret under `testui/`.
8. Build with a real key in `.env`, then `grep` `dist/` for that value — **must be absent**.
9. Drive `client.ts` from Node against the running backend: a health call produces a console record with every field populated, not undefined. A wrong key produces a recorded 401 distinguishable from a network failure, with no unhandled rejection.

**One open question — answer empirically, do not guess:**

10. Whether an HTTPS Vercel page can fetch `http://localhost:8001` is genuinely unclear to me — browsers have treated `http://localhost` as trustworthy for some purposes and Chrome's Private Network Access rules have been shifting. Test it if you can; if you cannot test it headlessly, say so and mark it unknown. **Do not write a confident claim either way into the README.** (It matters less now that the real path is the ngrok host over HTTPS, but testers may still try localhost.)

Finish with a **manual browser checklist, 6 items max**, for what you cannot verify headlessly — especially: opening the `?api=…&key=…` link works first time, the params vanish from the address bar, and the values survive a reload.

Delete verification scripts once they pass.

---

# Standing ground rules

1. No throwaway scripts left behind.
2. Detailed per-file change report, plus a short summary I can paste into my Cowork session.
3. Strict scope discipline. Flag anything outside scope, don't fix it. Fix bugs you introduce yourself.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly — check 10 is the model.
8. `aegle-abdm-core\` must not change. In `repo\`, **only `server/main.py`**. In `aegle-phr\`, only the access gate and CORS from Part 1, plus the new `testui/`.
9. Never print the access key or the client secret into your report.
