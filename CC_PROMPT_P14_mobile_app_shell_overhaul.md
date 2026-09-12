# P14 — Real mobile-app shell overhaul (replace test-harness/website chrome)

Aayush's own words: *"the app should not feel cluttered and busy... I want a nice minimal feel...
how can I demo this app to anyone."* He compared this app directly against ABDM's own official
sandbox PHR app (screenshots attached, see below) and it currently looks WORSE than that reference —
which he explicitly called "the basic standard," not the bar to just clear. This is a visual/layout
overhaul only — **no API calls, data-fetching logic, or business logic changes anywhere in this
prompt.** Every screen keeps doing exactly what it does today; only how it's laid out changes.

## Recommended model
Sonnet, extended thinking **ON** — same class of work as the earlier "Visual/Design overhaul" chunk
(2026-09-01, `lucide-react` + `ui/` primitives), which also used extended thinking: this touches many
files that all need to end up visually consistent with each other, and inconsistency between screens is
exactly the kind of mistake that's expensive to find later rather than while writing it.

## Look at the reference images directly — don't rely on the prose below alone
Five real screenshots from ABDM's own sandbox PHR app are saved in this repo at
`design_reference/01_home.png` through `05_profile.png`. **Open and actually look at all five before
writing any code** — the written description below is a starting point, not a substitute. Where the
prose and the images seem to disagree, the images win.

## Diagnosis — what's actually making this look like a website, not an app (confirmed by reading the current code)
1. **`testui/src/App.tsx`'s `<header>`** is a literal dev-harness title bar: `"Aegle PHR — Sandbox Test
   Harness"`, a "Show raw responses" checkbox, a light/dark toggle button, and a connection-status pill
   — all sitting in the main chrome, permanently visible on every screen.
2. **`.nav` in `App.tsx`** is a horizontal row of pill-shaped text+icon links (`Home`, `Profile`,
   `Consent Manager`, `Subscriptions`, `Providers`, `Logout`) that wraps onto multiple lines on a narrow
   viewport — a website nav bar, not a mobile bottom tab bar.
3. **`.app { max-width: 1180px; margin: 0 auto; ... }`** in `styles.css` — the whole app is laid out as a
   centered desktop container. There is no phone-frame width constraint and no mobile-first layout
   anywhere in this file today.
4. **`<fieldset><legend>...</legend>...</fieldset>` is the dominant sectioning pattern** — confirmed 70
   separate uses across the route files. This is a raw HTML form-sectioning element; it renders with a
   visible border and a legend tab that reads as "web form," never as an app card.
5. **The profile photo is a bare `<img>`**: `<img src={...} alt="Profile" style={{ maxWidth: 160 }} />`
   in `HomeScreen.tsx` — square, no crop, no banner, no positioning relative to the name/badges below it.
6. **ABHA Number/Address are plain paragraph text**: `<p className="result">ABHA Number:
   <code>{abhaNumber}</code></p>` — no icon, no label/value visual hierarchy, no card, nothing to
   distinguish it from a debug log line.
7. There already IS a real design-token system worth keeping (`styles.css`'s token block — teal
   `#154340` / amber `#CB9C30` / off-white `#E0DED1`, Quicksand font) and a small `ui/` primitive set
   (`Card`, `Button`, `Badge`, `PageHeader`, `EmptyState`, `CardGrid`) — but per that file's own banner,
   "not every screen's JSX was rewritten onto the new `ui-*` primitives," so the primitives and the old
   `fieldset`/`.result`/`.step` patterns coexist inconsistently. **Reuse and extend these tokens/
   primitives — don't invent a second palette or a second component system.**

## What the reference app does that this app should copy (from the 5 screenshots)
Common structure across all five reference screens:
- **A real native app shell**: a slim top bar (icon-only — menu/hamburger left, location pin +
  notification bell + profile icon right, no visible text title most of the time) and a **bottom tab
  bar** fixed to the screen bottom — icon + short label per tab, the active tab visually distinct
  (filled/colored icon), with the app's primary action (QR scan) as a **raised circular button sitting
  above the bar, centered**, not just another tab icon.
- **A profile header pattern**, reused verbatim between Home and Profile: a colored (teal, geometric
  pattern) banner strip, a circular profile photo overlapping the bottom edge of that banner, then
  centered below it: name (bold), a "KYC verified" badge with a green check icon, and a "Switch account"
  link in the accent color.
- **Key-value data as bordered rows/cards, never plain text**: ABHA Number and ABHA Address (image 1 and
  5), Date of Birth and Gender (image 5, two side-by-side half-width cards) are each their own rounded,
  bordered, subtly-shadowed row: a small icon on the left, a muted small label, and a bold value — never
  a `<p>` tag with a colon.
- **List rows with a leading icon (often in a colored square/circle) and a trailing chevron** — used for
  the hamburger menu (image 2: Health locker, Token history, Transaction history, ... Logout, each its
  own full-width row with consistent height and a divider) and for the facility list under search on Home.
- **Cards for list items with clear primary content + secondary actions**: the Linked Facilities list
  (image 4) — each facility is its own white rounded card, facility name bold, "Patient ID" as a small
  label/value pair beneath it, then a divider, then two icon+text action links side by side ("View
  Details", "Pull Records") — NOT full-width solid buttons stacked, and NOT crammed into a tiny row.
- **A segmented control for page-level tab state** — Consents (image 3) uses a filled pill switcher for
  "Requests" / "Approved" (the active one solid teal), and a second, lighter row of underline-style text
  tabs for the status filter (All/Pending/Denied/Expired) below it. This app's `ConsentScreen.tsx`
  already has this exact Requests/Approved + status-filter structure functionally (grep confirms it) —
  this is a restyle of existing logic, not new logic.
- **Friendly empty states**: a centered circular icon illustration plus one line of muted caption text
  ("We did not find any data at the moment") — `EmptyState` already exists in `components/ui/`, reuse
  and restyle it to match this look rather than adding a second empty-state component.
- **One dominant accent action per screen**: a full-width, solid, rounded-pill primary button ("Link new
  facility," "Scan & Share") in the brand accent color; everything secondary is an outline button or a
  plain icon+text link — never two solid buttons competing for attention on the same screen.
- **Generous whitespace, consistent row heights, minimal borders** — dividers appear only between list
  rows, not as a border around every single element the way `fieldset` currently renders.

## What to build
1. **New app shell in `App.tsx`**: replace the current `<header>`/`<nav>` pair with (a) a slim top bar
   (menu icon → opens a drawer/hamburger menu; keep the app accessible without one if that's simpler,
   but the icon-only top bar is the point) and (b) a real bottom tab bar, fixed position, for the 5
   primary logged-in destinations (Home, Profile or Health Locker naming to match this app's own
   sections, Consent Manager, Subscriptions, Providers) plus a raised circular action button if this app
   has an equivalent primary action (Scan & Share, from `ProfileScreen.tsx`, is the natural fit — surface
   it here the way the reference app surfaces QR scan). Logged-out routes (Login/Register/Create ABHA
   Address/Health) can keep something simpler since there's no "app" to navigate yet.
2. **Move dev/test-harness controls out of the main chrome, not out of the app.** This is still a test
   harness (per the standing directive: *"Test UI is a throwaway harness, NOT a product — BUT its
   design/navigation must read like a real app"*) — testers still need "Show raw responses," the theme
   toggle, the connection-status indicator, and Settings (base URL/access key). Put these inside the
   hamburger drawer/menu (mirroring image 2's Settings row) instead of pinned to every screen's header.
   Don't delete this functionality.
3. **New reusable primitives in `components/ui/`** (extend the existing set, matching its current
   conventions):
   - A `ProfileHeader` (banner + circular avatar + name + KYC badge + Switch-account link) — used by
     both `HomeScreen.tsx` and `ProfileScreen.tsx`, replacing their separate ad-hoc photo/name markup.
   - An `InfoRow` or `KeyValueCard` (icon + small label + bold value, bordered/shadowed) — replaces every
     `<p className="result">Label: <code>{value}</code></p>` pattern for ABHA Number/Address, DOB/Gender,
     and similar fields across `HomeScreen.tsx`/`ProfileScreen.tsx`.
   - A `ListRow` (leading icon, label, trailing chevron, full-width, consistent height) — for the
     hamburger drawer's menu items and the facility-name list under Home's search box.
   - A `SegmentedControl` (filled pill switcher) — for Consent's Requests/Approved and anywhere else a
     page-level two-state tab shows up.
   - A `BottomNav` and a slim `TopBar` component for the shell itself (used only by `App.tsx`).
   Check `EmptyState`/`Card`/`Button`/`Badge`/`PageHeader` first — reuse them inside these new
   primitives rather than duplicating their styling.
4. **Retire `<fieldset>`/`<legend>` as the sectioning pattern app-wide.** Replace with `Card`/`CardBody`
   (already used successfully in a few places, e.g. `HomeScreen.tsx`'s HIP-record cards) or a plain
   section + heading, per what the reference app actually does for that specific piece of content — don't
   mechanically fieldset→Card swap without checking the images for what that section should look like.
5. **`styles.css`**: drop the `max-width: 1180px` desktop-container rule on `.app` for the logged-in
   shell (or scope it so the bottom nav pins full-width while content stays comfortably readable) — this
   should read as a phone-width app, not a centered desktop page. Add token-based styles for the new
   primitives above, reusing the existing teal/amber/off-white tokens — no new colors invented.
6. **Apply the new primitives to every screen**, in this order (do Home and Profile first — they share
   `ProfileHeader`/`InfoRow`, so getting those two right validates the primitives before spreading them
   further):
   - `HomeScreen.tsx`: `ProfileHeader` for the photo/name/ABHA block, `InfoRow` for ABHA Number/Address,
     a real search-styled input (already has a facility filter — restyle it, don't rebuild it) over a
     `ListRow`-based facility list.
   - `ProfileScreen.tsx`: same `ProfileHeader`, `InfoRow` for DOB/Gender (side by side) and ABHA
     Number/Address, restyle the QR code card, Share/Download/Scan & Share buttons per the reference's
     button hierarchy (one solid primary, others outline).
   - `ConsentScreen.tsx`: `SegmentedControl` for Requests/Approved, restyle the existing status filter
     chips into the lighter underline-tab look, restyle `EmptyState` if needed to match image 3's look —
     no changes to the request/approve/deny/revoke logic itself.
   - `SubscriptionsScreen.tsx` (brand new from P13 — apply these primitives from the start rather than
     building it in the old style and redoing it) and `ProviderDirectoryScreen.tsx`: same card/list
     patterns, consistent with the rest.
7. **Do not touch**: any file under `repo/`, any `api/`/data-fetching code, any business logic in the
   route files beyond what's needed to swap markup/styling. If a screen's current behavior seems wrong
   while doing this (e.g., a filter that doesn't actually filter), leave it — flag it in the verification
   report instead of fixing it here.

## Constraints (standing, unchanged)
- Never delete or truncate `logs/`/`storage/` content.
- Don't modify `repo/`.
- This is CSS/markup/component work — no new ABDM API calls, no changes to `aegle_phr/` (the Python
  backend) at all.

## Verification
1. Take a screenshot of the new Home, Profile, Consent Manager (Requests tab, empty and non-empty if
   testable), and the hamburger drawer, at a phone-width viewport.
2. Put each screenshot side by side with its corresponding reference image
   (`design_reference/01_home.png`, `05_profile.png`, `03_consents.png`, `02_menu_drawer.png`) and report
   plainly where it still diverges — don't just assert "matches," actually compare and call out gaps.
3. Confirm nothing that used to work (login, fetching records, approving/denying consent, subscriptions)
   broke — this was meant to be styling-only; if anything's data-fetching regressed, that's a real bug to
   report, not an acceptable side effect of a visual pass.
4. Confirm the dev/test controls (raw responses toggle, theme toggle, status indicator, Settings) are
   still reachable somewhere, just not in the main chrome anymore.
