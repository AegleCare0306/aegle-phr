/**
 * Leading icon, label, trailing chevron -- full-width, consistent height,
 * for the hamburger drawer's menu items and any tap-through list (facility
 * names under Home's search, etc.) (P14). Polymorphic the same way Card is:
 * a plain `<button>` when `onClick` is given, an `<a>` when `href` is.
 */

import type { ButtonHTMLAttributes } from "react";
import { ChevronRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface ListRowOwnProps {
  icon?: LucideIcon;
  children: React.ReactNode;
  /** Trailing chevron, on by default -- turn off for a row that isn't navigational (rare). */
  chevron?: boolean;
}

export type ListRowProps = ListRowOwnProps & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children">;

export function ListRow({ icon: Icon, children, chevron = true, className = "", ...rest }: ListRowProps): JSX.Element {
  return (
    <button type="button" className={["ui-list-row", className].filter(Boolean).join(" ")} {...rest}>
      {Icon !== undefined && (
        <span className="ui-list-row__icon">
          <Icon size={18} aria-hidden="true" />
        </span>
      )}
      <span className="ui-list-row__label">{children}</span>
      {chevron && <ChevronRight size={16} className="ui-list-row__chevron" aria-hidden="true" />}
    </button>
  );
}
