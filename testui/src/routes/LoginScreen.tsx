/**
 * The landing page. Pure navigation — nothing here calls the backend.
 *
 * FIVE top-level options as of P1-E, not the original four: Mobile, ABHA
 * Number, ABHA Address, Aadhaar, Password. ABHA Address is the new one --
 * it had NO entry point at all before P1-E, because its two login methods
 * (§3.19-20, §3.21-22) are keyed by ABHA address, not by any of the
 * original four categories. Added as its own top-level option rather than
 * buried as a sub-choice under something else, since "which identifier are
 * you logging in with" is the natural top-level question this page asks,
 * and ABHA address is a distinct identifier from ABHA number, mobile, or
 * Aadhaar -- same tier as those three, not a variant of one of them.
 *
 * ABHA Number and ABHA Address both now lead to a sub-picker
 * (MethodChoiceScreen) rather than a terminal screen directly, since each
 * maps to two OTP channels. Mobile and Aadhaar still map directly to one
 * method each -- no sub-picker needed for those two.
 *
 * Password login (P1-C) is the one method with a real backend that isn't
 * one of the five -- it gets its own clearly separate entry point, same
 * tier as Register, since grouping it with the OTP methods would bury the
 * one login path that sends no SMS/email/UIDAI request at all. Register
 * itself is kept separate again: it is not a login method at all, it is
 * the escape hatch for someone with no ABHA address yet. Renamed from
 * "Enroll" in P1-F, when /enroll's real Aadhaar-based flow replaced the
 * old mobile-only form -- see App.tsx's own routing comment.
 */

import { AtSign, IdCard, LogIn, ScanFace, Smartphone, UserPlus } from "lucide-react";

import { ButtonLink } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";

export function LoginScreen(): JSX.Element {
  return (
    <section className="panel">
      <PageHeader icon={LogIn} title="Log in" description="Choose how you'd like to log in." />

      <div className="method-list">
        <ButtonLink variant="secondary" className="method-btn" icon={Smartphone} to="/login/mobile">Mobile</ButtonLink>
        <ButtonLink variant="secondary" className="method-btn" icon={IdCard} to="/login/abha-number">ABHA Number</ButtonLink>
        <ButtonLink variant="secondary" className="method-btn" icon={AtSign} to="/login/abha-address">ABHA Address</ButtonLink>
        <ButtonLink variant="secondary" className="method-btn" icon={ScanFace} to="/login/aadhaar">Aadhaar</ButtonLink>
      </div>

      <div className="login-options">
        <div className="login-option-row">
          <span className="muted">Have an ABHA address and password?</span>
          <ButtonLink size="sm" to="/login/password">Login with password</ButtonLink>
        </div>
        <div className="login-option-row">
          <span className="muted">Don&apos;t have an ABHA address?</span>
          <ButtonLink size="sm" icon={UserPlus} to="/register">Register</ButtonLink>
        </div>
      </div>
    </section>
  );
}
