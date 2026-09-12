/**
 * Banner + overlapping circular avatar + name + KYC badge + "Switch
 * account" link -- the profile-header pattern reused verbatim between
 * HomeScreen.tsx and ProfileScreen.tsx in the reference app (P14,
 * design_reference/01_home.png and 05_profile.png). Purely presentational:
 * every field is passed in, nothing fetched here.
 */

import { BadgeCheck, Repeat } from "lucide-react";

export interface ProfileHeaderProps {
  photoBase64: string;
  name: string;
  kycStatus: string;
  /** Hidden entirely (not shown-then-disabled) when the caller's own access rule says this session can't switch -- same convention ProfileScreen.tsx already uses for canSwitchProfile(). */
  onSwitchAccount?: () => void;
}

function kycTone(kycStatus: string): "success" | "warning" | "neutral" {
  return kycStatus === "VERIFIED" ? "success" : kycStatus === "" ? "neutral" : "warning";
}

export function ProfileHeader({ photoBase64, name, kycStatus, onSwitchAccount }: ProfileHeaderProps): JSX.Element {
  return (
    <div className="ui-profile-header">
      <div className="ui-profile-header__banner">
        <div className="ui-profile-header__avatar">
          {photoBase64 !== "" ? (
            <img src={`data:image/png;base64,${photoBase64}`} alt="" />
          ) : (
            <span className="ui-profile-header__avatar-fallback">{name.charAt(0).toUpperCase() || "?"}</span>
          )}
        </div>
      </div>
      <div className="ui-profile-header__body">
        <p className="ui-profile-header__name">{name}</p>
        {kycStatus !== "" && (
          <p className={`ui-profile-header__kyc ui-profile-header__kyc--${kycTone(kycStatus)}`}>
            <BadgeCheck size={14} aria-hidden="true" /> {kycStatus === "VERIFIED" ? "KYC verified" : kycStatus}
          </p>
        )}
        {onSwitchAccount !== undefined && (
          <button type="button" className="ui-profile-header__switch" onClick={onSwitchAccount}>
            <Repeat size={13} aria-hidden="true" /> Switch account
          </button>
        )}
      </div>
    </div>
  );
}
