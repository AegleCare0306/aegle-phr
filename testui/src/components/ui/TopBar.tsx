/**
 * Slim, icon-first top bar -- menu (hamburger) on the left, an optional
 * right-side slot -- replacing the old dev-harness title/checkbox/status
 * header (P14, design_reference/01_home.png: icon-only, no visible text
 * title most of the time). Each screen's own PageHeader still carries its
 * title in the content below; this bar stays constant across every
 * logged-in screen. Used only by App.tsx's AppShell.
 */

import { Menu } from "lucide-react";
import type { ReactNode } from "react";

export interface TopBarProps {
  onMenuClick: () => void;
  right?: ReactNode;
}

export function TopBar({ onMenuClick, right }: TopBarProps): JSX.Element {
  return (
    <header className="ui-top-bar">
      <button type="button" className="ui-top-bar__menu" onClick={onMenuClick} aria-label="Open menu">
        <Menu size={22} aria-hidden="true" />
      </button>
      <div className="ui-top-bar__brand">
        <span>Aegle Care</span>
      </div>
      {right !== undefined && <div className="ui-top-bar__right">{right}</div>}
    </header>
  );
}
