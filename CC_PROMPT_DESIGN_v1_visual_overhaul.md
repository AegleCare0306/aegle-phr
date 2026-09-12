# CC Prompt — Visual/Design overhaul, `aegle-phr` test UI (`testui/`)

**Model recommendation: Sonnet, extended thinking ON.** This isn't a hard reasoning problem, but it
touches every screen in the app and is easy to do inconsistently if rushed screen-by-screen without a
plan — extended thinking is for holding the whole design system in mind while touching ~11 files, not
for algorithmic difficulty.

## Why this chunk exists, and what it is NOT

Aayush's own words: *"the app looks really bad, no color, no alignment, it doesn't even meet the
basic requirements. It should be aligned. The boxes should be even sized. Icons should be used. You
are making [something] professional that should be accepted by today's standard."* This app won't go
into production, but it WILL be demoed to people, and right now it looks like a debug console — because
that's literally what it was built as (`styles.css`'s own top comment: *"One stylesheet, plain CSS, no
framework. Legible over attractive."*). That was the right call while the priority was proving ABDM
flows work at all. It's no longer the right call now that there's something to show people.

**This chunk is a pure visual/layout pass. It must not change:** any API call, any request/response
handling, any state logic, any routing structure or route paths, any of the raw-response / console /
debug-dump functionality that lets Aayush verify what ABDM actually returned (`RawBody.tsx`,
`ConsolePanel.tsx`, and every inline raw-JSON dump across screens) — restyle these, don't remove or
gut them, they're load-bearing for testing, not decoration. If a change to `className`/JSX structure
is needed to make something restyle cleanly, that's fine; a change to *what data flows where* is not
in scope here at all.

Standing ground rules for this project, still binding: never touch `repo/` (read-only reference);
never delete/truncate `logs/`/`storage/`; no git commit/push/init; never print secrets into any
report.

## Current state (confirmed by direct inspection, 2026-09-01)

- Plain React + react-router-dom, Vite, TypeScript. **Zero UI/CSS dependencies** — no Tailwind, no
  component library, no icon library. One hand-written `src/styles.css` (~200 lines).
- Palette today is essentially one accent blue (`#2b4ac7`) plus three semantic colors (ok/bad/warn)
  and a couple of grays. No real color system.
- Typography is one body size (15px) plus a handful of ad hoc smaller sizes, heavy reliance on
  monospace even for things that aren't data (labels, buttons in places).
- "Boxes not evenly sized" is real and mechanical: panels/cards (`.panel`, `.entry`, `.step`,
  `.user-item`, the request/artefact cards in Consent) size to their own content inside `flex`/`grid`
  containers with no `align-items: stretch` or fixed-height rule, so a row of cards with different
  content lengths renders with visibly uneven heights and no consistent internal rhythm (padding,
  gaps, radius all vary slightly panel to panel).
- No icons anywhere — pure text everywhere, including things that are begging for one: connection
  status dot (already color-coded, no icon), nav items, buttons, empty states, consent status chips
  (Pending/Granted/Denied/Expired/Revoked), login method tiles.
- 11 route screens confirmed: `LoginScreen`, `MethodChoiceScreen`, `MobileLoginScreen`,
  `OtpLoginScreen`, `PasswordLoginScreen`, `AadhaarRegisterScreen`, `AbhaAddressCreationScreen`,
  `HomeScreen`, `ProfileScreen`, `ConsentScreen`, `HealthScreen`, plus `NotBuiltYetScreen`. Shared
  components: `ConsolePanel`, `RawBody`, `SettingsPanel`, `StatusIndicator`.
- `ConsentScreen.tsx` (845 lines) and `ProfileScreen.tsx` (901 lines) are the two largest and most
  structurally complex screens — Consent's three-level drill-down (Requests/Approved tabs → request
  card → per-HIP artefact detail) and Profile's expand/collapse-per-feature panel pattern. Both are
  exactly the places uneven-card-sizing and missing icons will be most visible in a demo.
- `App.tsx`'s persistent nav currently shows Profile / Consent Manager / Logout when signed in
  (Login / Register / Create ABHA Address / Health when signed out) — note `HomeScreen` (the actual
  post-login landing page, per its own project history) has **no nav entry at all** once you navigate
  away from it. Not something Aayush asked to fix, but it's a one-line, zero-risk addition
  (`<NavLink to="/home">`) that directly serves "aligned, professional navigation" — add it, but call
  it out explicitly in your report as a small addition beyond pure restyling, not something to hide
  inside the diff.

## What to build

### 1. Design tokens (`src/styles.css`, keep it one file — don't fragment into CSS-in-JS)

Replace the current minimal `:root` block with a real system. Suggested starting values (adjust for
contrast/accessibility, but keep this shape — a proper scale, not a handful of one-off colors):

- **Color**: a neutral gray scale (bg/surface/border/text at 4-5 steps, not 2), a primary brand color
  in the blue/teal family (healthcare-appropriate, calm, trustworthy — not the current flat
  `#2b4ac7`; pick something with room for a hover/active shade and a light tint for backgrounds), and
  keep semantic success/warning/danger/info colors but make each a *pair* (a saturated color for
  text/icons, a light tint for backgrounds) so status badges and alerts read as intentional, not just
  colored text.
- **Typography scale**: page title, section heading, body, label/caption, and keep one monospace
  size for genuine data display (raw JSON, tokens, IDs) — don't eliminate monospace, just stop using
  it for things that aren't data.
- **Spacing scale**: a consistent 4px-based scale (4/8/12/16/24/32) used everywhere instead of the
  current ad hoc pixel values scattered through the stylesheet.
- **Radius + shadow scale**: 2-3 steps each. Panels/cards get a subtle shadow instead of a flat
  1px border only — this alone does a lot of the "professional" work.

### 2. Icon library

Install `lucide-react` (`npm install lucide-react` — run on Aayush's own machine, has normal network
access; this is a new dependency, first one beyond React itself). It's tree-shakeable, has a huge
free icon set, and is a standard, current choice for a React app — fits "accepted by today's
standard." Use it for: nav items (one icon per route), the connection status indicator (replace/pair
the color dot with a clear icon), primary buttons where an icon reinforces the action (approve/deny/
revoke, login methods, refresh), section headers in every panel, empty states (a large centered icon
+ message instead of a bare line of text), and status badges/chips (Pending/Granted/Denied/Expired/
Revoked in Consent; ok/error/network in the console log). Keep icon sizing consistent (e.g. 16px
inline with text, 20px in buttons/headers, one larger size for empty states) — pick one scale and use
it everywhere, don't eyeball sizes per screen.

### 3. Shared primitives (new files under `src/components/ui/`)

Build these once, then use them everywhere rather than hand-rolling markup per screen:
- `Card` — the one panel/box component every screen uses (replaces `.panel`, `.entry`, `.step`,
  `.user-item`, Consent's request/artefact cards, etc. — audit for near-duplicate box styles across
  the CSS and consolidate onto this one component with variants, not five almost-identical classes).
- `Button` — primary/secondary/ghost/danger variants × normal/small sizes, with an optional leading
  icon slot. Replaces `.btn`/`.btn--small`.
- `Badge`/`StatusPill` — for consent statuses, connection status, ok/error results. Icon + label,
  colored via the semantic pairs above.
- `PageHeader` — title + optional description + optional right-aligned actions, used at the top of
  every screen instead of each screen hand-rolling its own `<h1>`/`<h2>` layout.
- `EmptyState` — icon + message + optional action, for every "nothing here yet" case (no linked
  records, no consent requests, etc.).
- `CardGrid` — a grid wrapper that enforces equal-width AND equal-height cards in a row (this is the
  direct, mechanical fix for "boxes should be even sized" — `display:grid` with `align-items:stretch`
  and a `Card` that fills its grid cell height, not `flex`/inline layout that sizes to content).

### 4. Roll the design system out screen by screen

Go through every route listed above plus the shared components, applying the new tokens/primitives.
Do NOT rewrite the logic/state/API-calling code in any of them — this is markup + className + CSS
only. Suggested order (lowest-risk/most-mechanical first, so a build/typecheck failure is caught
early and is easy to localize):

1. Global chrome: `App.tsx`'s header/nav/footer, `StatusIndicator.tsx`.
2. Simple screens: `LoginScreen`, `MethodChoiceScreen`, `NotBuiltYetScreen`, `HealthScreen`.
3. Multi-step flows: `MobileLoginScreen`, `OtpLoginScreen`, `PasswordLoginScreen`,
   `AadhaarRegisterScreen`, `AbhaAddressCreationScreen` — these use the `.step`/`.row`/`.suggestions`
   patterns, consolidate onto `Card`/`Button`/spacing tokens.
4. `HomeScreen` (Linked Records list — this is the screen that most directly needs `CardGrid` for
   even-sized boxes) and `ProfileScreen` (expand/collapse panels → `Card` + consistent icon per
   section).
5. `ConsentScreen` last — the biggest and most structurally complex (three-level drill-down, status
   filter chips, tabs). Give it the most care: status chips → `Badge`, request/artefact cards →
   `Card` inside `CardGrid`, tab switcher restyled cleanly, the disabled-Approve-button explanation
   should read as an intentional inline notice (icon + text in a bordered callout), not a gray
   disabled button with a tooltip.
6. `ConsolePanel.tsx`/`RawBody.tsx` — restyle as a clearly-labeled "developer/raw response" area
   (monospace, slightly recessed background, collapsible) — keep it fully functional, make it look
   like an intentional debug panel rather than the accidental look of the rest of the app today.

### 5. Verify as you go, not just at the end

After each screen (or small batch), run `npm run typecheck && npm run build` before moving to the
next — this is a large diff across many files, and catching a broken screen early (while its own
change is still fresh) is much cheaper than debugging at the end across 11 files at once. Don't skip
this step to save time.

## What's explicitly NOT in scope here

- No new features, no new API endpoints, no change to what data is fetched or when.
- No change to routing structure, route paths, or the signed-in/signed-out nav split — other than the
  one explicitly-called-out `/home` nav link addition above.
- No change to session/auth/token logic.
- Don't touch anything under `repo/`.
- The Consent Approve-blocker fix (a HIP+care-context picker, discussed separately) is its own real
  feature chunk — not part of this visual pass. Leave the disabled state as-is functionally, just
  make it look intentional.

## Report back

Same format as prior chunks: which files you touched, what design decisions you made (exact color
values chosen, icon choices for anything ambiguous), whether `npm run build` passes clean, and a
screen-by-screen note of anything you deliberately left alone because restyling it risked touching
logic. Flag anything where the "even-sized boxes" fix required a genuine layout restructure (not just
a class swap) so Aayush knows where to look first when reviewing.
