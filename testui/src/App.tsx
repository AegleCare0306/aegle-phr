import { useEffect, useState, useSyncExternalStore } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Activity, AtSign, Bell, Building2, Home, IdCard, LogIn, LogOut, Mail, Moon, ScanFace, ShieldCheck, Smartphone, Sun, User, UserPlus } from "lucide-react";

import { ConsolePanel } from "./components/ConsolePanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { StatusIndicator } from "./components/StatusIndicator";
import { BottomNav } from "./components/ui/BottomNav";
import type { BottomNavItem } from "./components/ui/BottomNav";
import { ListRow } from "./components/ui/ListRow";
import { MenuDrawer } from "./components/ui/MenuDrawer";
import { TopBar } from "./components/ui/TopBar";
import {
  requestAadhaarOtp,
  requestAbhaAddressEmailOtp,
  requestAbhaAddressMobileOtp,
  requestAbhaNumberAadhaarOtp,
  requestAbhaNumberMobileOtp,
  verifyAadhaarOtp,
  verifyAbhaAddressEmailOtp,
  verifyAbhaAddressMobileOtp,
  verifyAbhaNumberAadhaarOtp,
  verifyAbhaNumberMobileOtp,
} from "./api/endpoints";
import { AadhaarRegisterScreen } from "./routes/AadhaarRegisterScreen";
import { AbhaAddressCreationScreen } from "./routes/AbhaAddressCreationScreen";
import { ConsentScreen } from "./routes/ConsentScreen";
import { HealthScreen } from "./routes/HealthScreen";
import { HomeScreen } from "./routes/HomeScreen";
import { LoginScreen } from "./routes/LoginScreen";
import { MethodChoiceScreen } from "./routes/MethodChoiceScreen";
import { MobileLoginScreen } from "./routes/MobileLoginScreen";
import { OtpLoginScreen } from "./routes/OtpLoginScreen";
import { PasswordLoginScreen } from "./routes/PasswordLoginScreen";
import { ProfileScreen } from "./routes/ProfileScreen";
import { ProviderDirectoryScreen } from "./routes/ProviderDirectoryScreen";
import { SubscriptionsScreen } from "./routes/SubscriptionsScreen";
import { UilLinkScreen } from "./routes/UilLinkScreen";
import { getConfig, isConfigured, setConfig } from "./config";
import type { AppConfig } from "./config";
import { getShowRawResponses, setShowRawResponses, subscribeShowRawResponses } from "./rawVisibility";
import { clearSession, getSessionToken, SESSION_EVENT } from "./session";
import { getTheme, subscribeTheme, toggleTheme } from "./theme";
import { useConnection } from "./useConnection";

/**
 * The app shell, rendered once and kept across every route.
 *
 * LAYOUT DECISION: status, settings and the console are debugging tools for
 * THIS HARNESS, not page content, so they stay mounted outside <Routes> and
 * are visible on every screen rather than being re-declared per route. Only
 * the area between the nav and the settings panel changes as you navigate.
 * A tester mid-flow on /enroll can still edit the key or read the console
 * without losing their place, and the connection check runs once regardless
 * of which route is current.
 */
/** The 5 primary logged-in destinations -- Consent Manager sits in the
 * middle and gets the reference app's raised-circular treatment (its own
 * equivalent of the reference's QR-scan button; nothing in this app is a
 * closer match for "the one action that deserves to stand out"). */
const PRIMARY_NAV: BottomNavItem[] = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/profile", label: "Profile", icon: User },
  { to: "/consent", label: "Consent", icon: ShieldCheck, raised: true },
  { to: "/subscriptions", label: "Subscriptions", icon: Bell },
  { to: "/providers", label: "Providers", icon: Building2 },
];

function AppShell(): JSX.Element {
  const [config, setLocalConfig] = useState<AppConfig>(() => getConfig());
  const { status, busy, check } = useConnection();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  // One automatic check on load, so a tester opening their link sees the
  // answer without pressing anything.
  useEffect(() => {
    if (isConfigured(config)) void check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reactive login state (Aayush's explicit request): the nav below
  // switches to Profile/Logout only once logged in. Session state lives
  // in sessionStorage, written by whichever login screen the tester used
  // -- SESSION_EVENT (see session.ts) is what lets THIS component notice
  // a login/logout that happened inside a completely different screen's
  // local state, without threading a callback through every one of them.
  const [loggedIn, setLoggedIn] = useState(() => getSessionToken() !== "");
  useEffect(() => {
    const onSessionChanged = (): void => setLoggedIn(getSessionToken() !== "");
    window.addEventListener(SESSION_EVENT, onSessionChanged);
    return () => window.removeEventListener(SESSION_EVENT, onSessionChanged);
  }, []);

  const save = (next: AppConfig): void => {
    setConfig(next);
    setLocalConfig(getConfig());
    void check();
  };

  const logout = (): void => {
    clearSession();
    navigate("/login");
  };

  // Aayush's explicit request: one global, live toggle -- OFF hides every
  // inline "raw ABDM response" block across every screen, ON shows all of
  // them, switchable mid-flow with no reload. See rawVisibility.ts and
  // components/RawBody.tsx (the single shared component this reaches)
  // for why "no exceptions" is actually enforceable here.
  const showRaw = useSyncExternalStore(subscribeShowRawResponses, getShowRawResponses, getShowRawResponses);

  // Light/dark toggle for the Option B (Quicksand) palette -- see theme.ts.
  // Same subscribe/emit shape as showRaw above, so the button and any other
  // reader stay in sync with no reload.
  const theme = useSyncExternalStore(subscribeTheme, getTheme, getTheme);
  const isDark = theme === "dark";

  return (
    <div className="app">
      <TopBar onMenuClick={() => setMenuOpen(true)} />

      <MenuDrawer open={menuOpen} onClose={() => setMenuOpen(false)}>
        {/* Direct jumps for testing -- every route is still reachable by URL
            regardless of what's shown here. LOGGED OUT: no bottom nav yet
            (nothing to navigate within an "app" the tester hasn't entered),
            so the four entry points that used to live in the old top nav
            move here instead. LOGGED IN: these same 5 destinations already
            live in the bottom tab bar, so the drawer's own nav section is
            just Logout -- repeating all 5 here too would just be the old
            cluttered nav bar relocated, not fixed. */}
        {!loggedIn && (
          <div className="ui-menu-drawer__section">
            <p className="ui-menu-drawer__section-title">Get started</p>
            <ListRow icon={LogIn} onClick={() => { setMenuOpen(false); navigate("/login"); }}>Login</ListRow>
            <ListRow icon={UserPlus} onClick={() => { setMenuOpen(false); navigate("/register"); }}>Register</ListRow>
            <ListRow icon={IdCard} onClick={() => { setMenuOpen(false); navigate("/create-address"); }}>Create ABHA Address</ListRow>
            <ListRow icon={Activity} onClick={() => { setMenuOpen(false); navigate("/health"); }}>Health</ListRow>
          </div>
        )}
        {loggedIn && (
          <div className="ui-menu-drawer__section">
            <ListRow icon={LogOut} onClick={() => { setMenuOpen(false); logout(); }}>Logout</ListRow>
          </div>
        )}

        {/* Test-harness controls -- still here, just no longer pinned to
            every screen's header (P14, standing directive: "design/
            navigation must read like a real app" without losing any of
            this functionality). */}
        <div className="ui-menu-drawer__section">
          <p className="ui-menu-drawer__section-title">Test harness</p>
          <label className="ui-list-row" style={{ cursor: "pointer" }}>
            <span className="ui-list-row__label">
              <span className="checkbox">
                <input
                  type="checkbox"
                  checked={showRaw}
                  onChange={(event) => setShowRawResponses(event.target.checked)}
                />
                Show raw responses
              </span>
            </span>
          </label>
          <ListRow
            icon={isDark ? Sun : Moon}
            chevron={false}
            onClick={toggleTheme}
          >
            {isDark ? "Switch to light mode" : "Switch to dark mode"}
          </ListRow>
        </div>

        <div className="ui-menu-drawer__section">
          <p className="ui-menu-drawer__section-title">Connection</p>
          <StatusIndicator status={status} onRecheck={() => void check()} busy={busy} />
        </div>

        <div className="ui-menu-drawer__section">
          <SettingsPanel config={config} onSave={save} />
        </div>
      </MenuDrawer>

      <div className="app__content">
        {!isConfigured(config) && (
          <p className="notice">
            No backend URL or access key set. Open the link you were sent — it looks like
            <code>{" https://…/?api=https://…&key=…"}</code> — or set them under Settings (menu, top left).
          </p>
        )}

        <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />

          {/* Post-login landing page (Aayush's explicit request): every
              login screen navigates here on success instead of showing
              its own inline "Logged in as ..." view. See HomeScreen.tsx's
              own banner. */}
          <Route path="/home" element={<HomeScreen />} />

          <Route path="/login" element={<LoginScreen />} />
          <Route path="/login/mobile" element={<MobileLoginScreen />} />

          {/* ABHA Number splits into two OTP channels (spec §3.13-14 vs
              §3.17-18) -- a sub-picker rather than folding a channel choice
              into one screen, per P1-E's navigation decision (see the
              change report). */}
          <Route
            path="/login/abha-number"
            element={
              <MethodChoiceScreen
                title="ABHA Number login"
                prompt="How would you like to receive your OTP?"
                options={[
                  { label: "Aadhaar OTP", to: "/login/abha-number/aadhaar-otp", icon: ScanFace },
                  { label: "Mobile OTP", to: "/login/abha-number/mobile-otp", icon: Smartphone },
                ]}
              />
            }
          />
          <Route
            path="/login/abha-number/aadhaar-otp"
            element={
              <OtpLoginScreen
                title="ABHA Number login (Aadhaar OTP)"
                icon={IdCard}
                otpChannelDescription="real OTP to your Aadhaar-registered mobile"
                identifierLabel="ABHA Number"
                identifierPlaceholder="14-digit ABHA number"
                maskIdentifier
                loginMethod="abha-number"
                requestOtp={(identifier) => requestAbhaNumberAadhaarOtp({ abhaNumber: identifier })}
                verifyOtp={verifyAbhaNumberAadhaarOtp}
              />
            }
          />
          <Route
            path="/login/abha-number/mobile-otp"
            element={
              <OtpLoginScreen
                title="ABHA Number login (Mobile OTP)"
                icon={IdCard}
                otpChannelDescription="real SMS to the mobile linked to this ABHA number"
                identifierLabel="ABHA Number"
                identifierPlaceholder="14-digit ABHA number"
                maskIdentifier
                loginMethod="abha-number"
                requestOtp={(identifier) => requestAbhaNumberMobileOtp({ abhaNumber: identifier })}
                verifyOtp={verifyAbhaNumberMobileOtp}
              />
            }
          />

          {/* ABHA Address had NO existing entry point before P1-E -- both
              of its methods (§3.19-20, §3.21-22) are keyed by ABHA address,
              not by any of the original four top-level categories. Added
              as a fifth top-level option on /login (see LoginScreen.tsx)
              rather than burying it as a sub-choice under something else,
              since it is a distinct identifier type, same tier as Mobile /
              ABHA Number / Aadhaar. */}
          <Route
            path="/login/abha-address"
            element={
              <MethodChoiceScreen
                title="ABHA Address login"
                prompt="How would you like to receive your OTP?"
                options={[
                  { label: "Mobile OTP", to: "/login/abha-address/mobile-otp", icon: Smartphone },
                  { label: "Email OTP", to: "/login/abha-address/email-otp", icon: Mail },
                ]}
              />
            }
          />
          <Route
            path="/login/abha-address/mobile-otp"
            element={
              <OtpLoginScreen
                title="ABHA Address login (Mobile OTP)"
                icon={AtSign}
                otpChannelDescription="real SMS"
                identifierLabel="ABHA Address"
                identifierPlaceholder="yourname@sbx"
                identifierAutoComplete="username"
                maskIdentifier={false}
                loginMethod="abha-address"
                singleAccount
                requestOtp={(identifier) => requestAbhaAddressMobileOtp({ abhaAddress: identifier })}
                verifyOtp={verifyAbhaAddressMobileOtp}
              />
            }
          />
          <Route
            path="/login/abha-address/email-otp"
            element={
              <OtpLoginScreen
                title="ABHA Address login (Email OTP)"
                icon={AtSign}
                otpChannelDescription="real email"
                identifierLabel="Email"
                identifierPlaceholder="you@example.com"
                identifierAutoComplete="email"
                maskIdentifier={false}
                loginMethod="abha-address"
                singleAccount
                requestOtp={(identifier) => requestAbhaAddressEmailOtp({ email: identifier })}
                verifyOtp={verifyAbhaAddressEmailOtp}
              />
            }
          />

          {/* Raw Aadhaar Number login (§3.15-16) maps directly onto the
              existing Aadhaar option -- no sub-picker needed, it is one
              method. Replaces the "Not built yet" stub from P1-B. */}
          <Route
            path="/login/aadhaar"
            element={
              <OtpLoginScreen
                title="Aadhaar login"
                icon={ScanFace}
                otpChannelDescription="real OTP via UIDAI"
                identifierLabel="Aadhaar Number"
                identifierPlaceholder="12-digit Aadhaar number"
                maskIdentifier
                loginMethod="aadhaar-number"
                requestOtp={(identifier) => requestAadhaarOtp({ aadhaarNumber: identifier })}
                verifyOtp={verifyAadhaarOtp}
              />
            }
          />

          <Route path="/login/password" element={<PasswordLoginScreen />} />

          {/* P1-F: "Register" now means real Aadhaar-based ABHA Number
              creation, replacing the old mobile-based enrol() form that
              used to live at /enroll. Picked /register over keeping
              /enroll, since the nav link itself is renamed. P1-G: this
              flow ends once the ABHA Number/Address exist -- password is
              a LOGIN mechanism, not part of registration, so there is no
              password step here (an earlier version of this chunk tried
              one, built on the wrong ABDM endpoint; removed, not
              replaced -- see AadhaarRegisterScreen.tsx's own banner). */}
          <Route path="/register" element={<AadhaarRegisterScreen />} />

          {/* P1-H: Aayush's third top-level entry point, distinct from
              both Login and Signup -- already have an ABHA Number, want an
              ABHA Address for it. Two ownership-verification methods, each
              built exactly as Aayush's own Postman collection shows it --
              see AbhaAddressCreationScreen.tsx's own banner. */}
          <Route
            path="/create-address"
            element={
              <MethodChoiceScreen
                title="Create ABHA Address"
                prompt="How would you like to verify ownership of your ABHA Number?"
                options={[
                  { label: "Aadhaar OTP", to: "/create-address/aadhaar-otp", icon: ScanFace },
                  { label: "Mobile OTP", to: "/create-address/mobile-otp", icon: Smartphone },
                ]}
              />
            }
          />
          <Route path="/create-address/aadhaar-otp" element={<AbhaAddressCreationScreen method="aadhaar" />} />
          <Route path="/create-address/mobile-otp" element={<AbhaAddressCreationScreen method="mobile" />} />

          {/* P1-M: the first screen whose entire purpose IS the logged-in
              state -- see ProfileScreen.tsx's own banner. Reads the same
              session.ts every login screen already writes to; shows a
              plain "log in first" message if empty. */}
          <Route path="/profile" element={<ProfileScreen />} />

          {/* Consent Manager -- all 11 patient-facing consent flows
              (spec §6). Its own screen, not an inline Home section --
              see ConsentScreen.tsx's own banner. Reachable from the nav
              above and from a button on HomeScreen.tsx. */}
          <Route path="/consent" element={<ConsentScreen />} />

          {/* Subscription Flow (spec §8) -- P13, its own screen, not an
              inline Home section -- see SubscriptionsScreen.tsx's own
              banner. Reachable from the nav above, same tier as Consent
              Manager. */}
          <Route path="/subscriptions" element={<SubscriptionsScreen />} />

          {/* Provider Directory (spec §10.3.13-15) -- stateless, read-only
              global directory lookup, no patient session needed at all --
              see ProviderDirectoryScreen.tsx's own banner. Nav entry lives
              in the signed-in list per the task prompt, but the route
              itself needs no session and would work identically logged
              out. */}
          <Route path="/providers" element={<ProviderDirectoryScreen />} />

          {/* User-Initiated Linking (spec §10.3.1-§10.3.12) -- P15, "Find
              my records". Entry point is a "Link this facility" button on
              a ProviderDirectoryScreen.tsx result, not a route a tester
              has to already know -- see UilLinkScreen.tsx's own banner for
              the full continuous discover -> review -> OTP -> confirm
              flow this one route covers. */}
          <Route path="/link/:hipId" element={<UilLinkScreen />} />

          <Route path="/health" element={<HealthScreen />} />
          {/* Unknown paths land on login rather than a dead end. */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>

        <ConsolePanel />
        </main>

        <footer className="footer muted">
          Temporary test harness for the ABDM sandbox. Not a product, not for real patient data.
        </footer>
      </div>

      {loggedIn && <BottomNav items={PRIMARY_NAV} />}
    </div>
  );
}

export function App(): JSX.Element {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
