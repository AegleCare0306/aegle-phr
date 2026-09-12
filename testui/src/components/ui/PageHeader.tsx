/**
 * Title + optional description + optional right-aligned actions, used at
 * the top of every screen instead of each one hand-rolling its own
 * <div className="panel__head"><h2>...</h2></div> layout.
 */

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export interface PageHeaderProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ icon: Icon, title, description, actions }: PageHeaderProps): JSX.Element {
  return (
    <div className="ui-page-header">
      <div className="ui-page-header__main">
        {Icon !== undefined && (
          <span className="ui-page-header__icon">
            <Icon size={20} aria-hidden="true" />
          </span>
        )}
        <div>
          <h2 className="ui-page-header__title">{title}</h2>
          {description !== undefined && <p className="ui-page-header__description">{description}</p>}
        </div>
      </div>
      {actions !== undefined && <div className="ui-page-header__actions">{actions}</div>}
    </div>
  );
}
