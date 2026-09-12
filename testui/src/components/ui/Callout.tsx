/**
 * Icon + text in a bordered box, for an inline notice that needs to read
 * as intentional -- e.g. Consent's disabled-Approve explanation -- rather
 * than a plain gray disabled button with no context.
 */

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Info } from "lucide-react";

export interface CalloutProps {
  icon?: LucideIcon;
  tone?: "info" | "warning";
  children: ReactNode;
}

export function Callout({ icon: Icon = Info, tone = "info", children }: CalloutProps): JSX.Element {
  return (
    <div className={`ui-callout${tone === "warning" ? " ui-callout--warning" : ""}`}>
      <Icon size={16} className="ui-callout__icon" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
