# Aegle PHR — test harness UI

A deliberately small React + TypeScript app for driving ABDM **sandbox**
flows against the PHR backend. Temporary, throwaway, not a product.

Its real job is not the screens. It is the **Console**: every HTTP call the
app makes is recorded with full request and response detail, so a flow can be
debugged from a screenshot.

Real client-side routing (React Router) as of P1-B: `/login` is the landing
page, offering Mobile / ABHA Number / Aadhaar as separate real routes (none
of their backends exist yet — each honestly says so, rather than faking a
flow) plus a distinct "Enroll" path to `/enroll` for someone with no ABHA
address. `/health` is a diagnostic route, reachable from the nav bar.

## The link is the whole UX

Testers install nothing, run nothing, host nothing. They get one link:

```
https://<app>.vercel.app/?api=https://<ngrok-host>&key=<shared-key>
```

On first load the app saves `api` and `key` to `localStorage`, then strips
them from the address bar with `history.replaceState` so a screenshot or a
shared tab does not leak the key. After that the plain URL works.

Settings lets both values be edited by hand (key as a password field) for
when the ngrok host changes.

> **The backend and the ngrok tunnel must be running on Aayush's machine.**
> This is a tunnel to a laptop, not a deployment. When that machine is off,
> testers get "Unreachable" — inherent to the setup, not a bug.

### `?api=http://localhost:…` does not work from the deployed page

Measured, not assumed — in one Chromium build, with a control run to rule out
reachability:

| Page origin | `fetch("http://localhost:8001")` |
|---|---|
| `https://…` | fails ("Failed to fetch") |
| `http://…` | succeeds |

Only the page's scheme differed; same browser, same server, same CORS. So a
tester on the HTTPS Vercel page **cannot** point `api` at their own
`localhost` — use the ngrok HTTPS host. Scope: this was one Chromium-family
browser, not Firefox or Safari, and not the real Vercel deployment. Pointing
`api` at localhost still works when the UI itself is served over HTTP
(`npm run dev`).

## Running locally

```bash
npm install
npm run dev
```

Then open `http://localhost:5173/?api=http://localhost:8000&key=<key>`.

Port 8000, not 8001: the PHR router is mounted into the existing ABDM
backend, because there is only one ngrok domain and it points at 8000.
Running `python -m aegle_phr` on 8001 also works for backend-only testing.

`npm run build` runs `tsc --noEmit` first, so a type error fails the build.

## Deploying to Vercel

- **Root Directory must be `testui`** (Project → Settings → General). Without
  it Vercel builds the repository root and finds no `package.json`.
- Framework preset: Vite. Build `npm run build`, output `dist`.
- **No environment variables.** The key must never be baked into the build —
  there is no `VITE_*` default and no key in source. Anything in a Vercel
  bundle is public.
- **`vercel.json` IS needed, as of P1-B.** The app now has client-side routes
  (`/login`, `/enroll`, `/health`, …) via React Router. A direct load or
  refresh of any of those paths is a request to Vercel's static host for a
  file that doesn't exist, unless every path is rewritten to `index.html` so
  the client-side router can take over. The committed `vercel.json` does
  exactly that (`"/(.*)" → "/index.html"`). Confirmed locally against Vite's
  dev-server fallback, which behaves the same way; not yet confirmed against
  a real Vercel deploy.

## Architecture — the one rule

**`fetch()` appears in exactly one file: `src/api/client.ts`.**

A screen that calls `fetch` directly silently opts out of the Console, which
is the only reason this app exists.

```
src/
  main.tsx              consumes ?api / ?key BEFORE the router mounts, then renders
  App.tsx               BrowserRouter + persistent shell (nav, status, settings, console) + <Routes>
  config.ts             localStorage + URL-parameter handling
  useConnection.ts      reachable / unauthorized / unreachable, from a real call
  api/
    client.ts           THE ONLY fetch(). Attaches X-Aegle-Key, records everything
    endpoints.ts        one function per backend endpoint
    consoleStore.ts     in-memory record store (never localStorage)
    types.ts            ConsoleRecord, ApiResult
  components/           StatusIndicator, ConsolePanel, SettingsPanel
  routes/                one file per route
    LoginScreen.tsx      /login -- method picker, pure navigation, no backend calls
    AadhaarRegisterScreen.tsx  /register -- real Aadhaar-based ABHA creation, ends at the ABHA Number/Address (P1-F/P1-G)
    HealthScreen.tsx     /health
```

**Persistent shell, since P1-B:** status, Settings and the Console live in
`AppShell` (`App.tsx`), outside `<Routes>`, so they stay visible and keep
their own state across every route — a tester mid-flow on `/register` can edit
the key or read a past call without losing their place. Only the content
between the nav bar and the Settings panel changes as you navigate. Route
components keep their OWN local state (e.g. `AadhaarRegisterScreen`'s form fields),
which resets on remount like any React component — that's normal, not a bug.

**Session/token storage — not yet decided.** There is no logged-in state in
this app yet; nothing currently needs to persist a session. When the first
authenticated flow lands (password login is next), where its token lives is
a real design decision, not an extension of `config.ts`'s pattern — the
`enrol` response in P1-A already showed `tokens.token`/`refreshToken` are
JWTs whose claims embed PII (mobile, full name, DOB), which rules out
treating them like the access key (localStorage, `••••`-masked in the
Console) without thinking through what a screenshot of a "logged in" Console
entry would expose.

Console records are **in memory only**. Response bodies contain OTPs and
tokens; only the backend URL and the key are persisted. The key is masked to
`••••` when the record is *created*, so the store never holds it.

## Adding a route (this is the P1 path)

**1 — add the endpoint** in `src/api/endpoints.ts`:

```ts
export interface RequestOtpBody { mobile: string }
export interface RequestOtpResponse { txnId: string }

export function requestOtp(body: RequestOtpBody): Promise<ApiResult<RequestOtpResponse>> {
  return apiRequest<RequestOtpResponse>("/phr/login/otp/request", { method: "POST", body });
}
```

That is all the HTTP you write. The key, the base URL, timing, and the
console record are handled.

**2 — add the screen** in `src/routes/`, modelled on `HealthScreen.tsx`
(a screen with no state machine) or `AadhaarRegisterScreen.tsx` (one with
several steps and a raw, undocumented-shape response):

```tsx
export function OtpScreen(): JSX.Element {
  const [result, setResult] = useState<ApiResult<RequestOtpResponse> | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (): Promise<void> => {
    setBusy(true);
    try { setResult(await requestOtp({ mobile })); } finally { setBusy(false); }
  };
  // render result.data on success, result.errorMessage otherwise
}
```

**3 — register the route** in `App.tsx`'s `<Routes>` block:

```tsx
<Route path="/login/otp" element={<OtpScreen />} />
```

Add a link to it from wherever a tester should reach it (`LoginScreen.tsx`
for a login method, the persistent `<nav>` for something reachable anytime).
If the route replaces one of the `NotBuiltYetScreen` placeholders (e.g.
`/login/mobile`), swap the `element=` in place — the path stays the same, so
nothing that already links to it needs to change.

Handle all three outcomes: `result.kind` is `"success"`, `"http-error"` (the
server answered — a 401 means a stale key) or `"network-error"` (nothing
answered — tunnel down or CORS). Never collapse them into one message; a
tester with a stale key must be able to tell.

## What this app deliberately does not do

- Never talks to ABDM directly. No ABDM URLs, no client id, no client secret,
  no crypto in the browser. It calls the PHR backend and nothing else.
- No component library, no Tailwind. One plain CSS file.
- No fake success states. `/login/mobile`, `/login/abha-number` and
  `/login/aadhaar` are real routes that plainly say their backend does not
  exist yet — not a spinner that goes nowhere, not a placeholder pretending
  to be a flow.
- No post-login Home/Dashboard. Nothing produces a session yet, so there is
  no logged-in destination to build until the first flow that creates one.
