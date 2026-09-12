/**
 * Large centered icon + message (+ optional action) for every "nothing
 * here yet" case -- no linked records, no consent requests, empty console,
 * etc. -- instead of a bare line of muted text.
 */

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export interface EmptyStateProps {
  icon: LucideIcon;
  message: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, message, action }: EmptyStateProps): JSX.Element {
  return (
    <div className="ui-empty">
      <Icon size={32} className="ui-empty__icon" aria-hidden="true" />
      <p className="ui-empty__message">{message}</p>
      {action}
    </div>
  );
}
