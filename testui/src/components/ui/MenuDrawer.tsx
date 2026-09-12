/**
 * Full-screen menu overlay opened from TopBar's hamburger (P14,
 * design_reference/02_menu_drawer.png: dark header with a grid icon +
 * "Menu" + close, a plain scrollable list below). A pure shell -- App.tsx
 * supplies the actual rows (nav shortcuts, dev/test-harness controls) as
 * children, since this component has no business of knowing about
 * sessions/config/theme itself.
 */

import { LayoutGrid, X } from "lucide-react";
import type { ReactNode } from "react";

export interface MenuDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function MenuDrawer({ open, onClose, children }: MenuDrawerProps): JSX.Element | null {
  if (!open) return null;
  return (
    <div className="ui-menu-drawer" role="dialog" aria-modal="true" aria-label="Menu">
      <header className="ui-menu-drawer__header">
        <span className="ui-menu-drawer__title">
          <LayoutGrid size={18} aria-hidden="true" /> Menu
        </span>
        <button type="button" className="ui-menu-drawer__close" onClick={onClose} aria-label="Close menu">
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      <div className="ui-menu-drawer__body">{children}</div>
    </div>
  );
}
