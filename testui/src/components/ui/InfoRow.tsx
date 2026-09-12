/**
 * Icon + small muted label + bold value, as a bordered/shadowed row --
 * replaces every `<p className="result">Label: <code>{value}</code></p>`
 * pattern (P14). Used both full-width (ABHA Number/Address, wrapped in
 * `.ui-info-stack`) and side by side (DOB/Gender, wrapped in
 * `.ui-info-split` -- see ProfileScreen.tsx) -- the two-up layout is the
 * wrapper's job, not a prop on the row itself.
 */

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export interface InfoRowProps {
  icon?: LucideIcon;
  label: string;
  value: ReactNode;
  /** Trailing slot, e.g. a small preferred/verified marker. */
  trailing?: ReactNode;
}

export function InfoRow({ icon: Icon, label, value, trailing }: InfoRowProps): JSX.Element {
  return (
    <div className="ui-info-row">
      {Icon !== undefined && (
        <span className="ui-info-row__icon">
          <Icon size={18} aria-hidden="true" />
        </span>
      )}
      <div className="ui-info-row__text">
        <span className="ui-info-row__label">{label}</span>
        <span className="ui-info-row__value">{value}</span>
      </div>
      {trailing !== undefined && <span className="ui-info-row__trailing">{trailing}</span>}
    </div>
  );
}
