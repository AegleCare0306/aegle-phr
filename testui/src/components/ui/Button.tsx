/**
 * Replaces .btn/.btn--small with a proper variant+size system and an
 * optional leading icon slot. buttonClassName() is exported separately so
 * ButtonLink (react-router's <Link>, which can't be a <button>) renders
 * pixel-identical to Button rather than hand-rolling its own class list.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { LinkProps } from "react-router-dom";
import { Link } from "react-router-dom";
import type { LucideIcon } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

export function buttonClassName(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className = ""): string {
  return ["ui-btn", `ui-btn--${variant}`, `ui-btn--${size}`, className].filter(Boolean).join(" ");
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  children?: ReactNode;
}

export function Button({ variant = "secondary", size = "md", icon: Icon, className = "", children, ...rest }: ButtonProps): JSX.Element {
  return (
    <button className={buttonClassName(variant, size, className)} {...rest}>
      {Icon !== undefined && <Icon size={size === "sm" ? 14 : 16} className="ui-btn__icon" aria-hidden="true" />}
      {children}
    </button>
  );
}

export interface ButtonLinkProps extends LinkProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
}

export function ButtonLink({ variant = "secondary", size = "md", icon: Icon, className = "", children, ...rest }: ButtonLinkProps): JSX.Element {
  return (
    <Link className={buttonClassName(variant, size, className)} {...rest}>
      {Icon !== undefined && <Icon size={size === "sm" ? 14 : 16} className="ui-btn__icon" aria-hidden="true" />}
      {children}
    </Link>
  );
}
