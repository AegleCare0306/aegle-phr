/**
 * Icon + label status pill -- consent statuses, connection status, and
 * console log outcomes all route through this one component so a status
 * reads as intentional (color pair + icon), not just colored text.
 */

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral";

export interface BadgeProps {
  tone?: BadgeTone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}

export function Badge({ tone = "neutral", icon: Icon, children, className = "" }: BadgeProps): JSX.Element {
  return (
    <span className={["ui-badge", `ui-badge--${tone}`, className].filter(Boolean).join(" ")}>
      {Icon !== undefined && <Icon size={12} aria-hidden="true" />}
      {children}
    </span>
  );
}
