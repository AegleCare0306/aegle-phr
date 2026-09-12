/**
 * Fixed bottom tab bar for the 5 primary logged-in destinations, with one
 * tab optionally raised into a circular accent button -- the reference
 * app's QR-scan treatment (P14, design_reference/01_home.png). Used only
 * by App.tsx's AppShell.
 */

import { NavLink } from "react-router-dom";
import type { LucideIcon } from "lucide-react";

export interface BottomNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Renders as an elevated circular button instead of a flat tab -- the reference app's own QR-scan treatment. At most one item should set this. */
  raised?: boolean;
}

export function BottomNav({ items }: { items: BottomNavItem[] }): JSX.Element {
  return (
    <nav className="ui-bottom-nav">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            [
              "ui-bottom-nav__item",
              item.raised === true ? "ui-bottom-nav__item--raised" : "",
              isActive ? "ui-bottom-nav__item--active" : "",
            ]
              .filter(Boolean)
              .join(" ")
          }
        >
          <span className="ui-bottom-nav__icon">
            <item.icon size={item.raised === true ? 22 : 19} aria-hidden="true" />
          </span>
          <span className="ui-bottom-nav__label">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
