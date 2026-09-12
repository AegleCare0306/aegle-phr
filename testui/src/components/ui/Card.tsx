/**
 * The one panel/box primitive every screen should use going forward --
 * consolidates what used to be five near-identical box styles (.panel,
 * .entry, .step, .user-item, Consent's own request/artefact cards) onto
 * one component with variants. Polymorphic via `as` specifically so a
 * `<fieldset disabled={busy}>` step -- load-bearing behaviour, it disables
 * every input inside while a request is in flight -- can become
 * `<Card as="fieldset" disabled={busy}>` without losing that behaviour.
 */

import type { ElementType, FieldsetHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface CardOwnProps {
  children: ReactNode;
  padding?: "sm" | "md" | "lg";
  /** Hover elevation + pointer cursor, for a card that's itself clickable (e.g. "View details" cards). */
  interactive?: boolean;
  /** Drop the shadow and tighten the radius -- for a card nested inside another card. */
  flush?: boolean;
  className?: string;
}

type CardAsDiv = CardOwnProps & { as?: "div" } & HTMLAttributes<HTMLDivElement>;
type CardAsSection = CardOwnProps & { as: "section" } & HTMLAttributes<HTMLElement>;
type CardAsFieldset = CardOwnProps & { as: "fieldset" } & FieldsetHTMLAttributes<HTMLFieldSetElement>;

export type CardProps = CardAsDiv | CardAsSection | CardAsFieldset;

export function Card(props: CardProps): JSX.Element {
  const { as = "div", children, padding = "md", interactive = false, flush = false, className = "", ...rest } =
    props as CardOwnProps & { as?: ElementType } & Record<string, unknown>;
  const Comp = as;
  const classes = [
    "ui-card",
    `ui-card--pad-${padding}`,
    interactive ? "ui-card--interactive" : "",
    flush ? "ui-card--flush" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <Comp className={classes} {...rest}>
      {children}
    </Comp>
  );
}

export function CardHeader({ children }: { children: ReactNode }): JSX.Element {
  return <div className="ui-card__header">{children}</div>;
}

export function CardTitle({ icon: Icon, children }: { icon?: LucideIcon; children: ReactNode }): JSX.Element {
  return (
    <h3 className="ui-card__title">
      {Icon !== undefined && <Icon size={16} aria-hidden="true" />}
      {children}
    </h3>
  );
}

export function CardBody({ children }: { children: ReactNode }): JSX.Element {
  return <div className="ui-card__body">{children}</div>;
}

export function CardFooter({ children }: { children: ReactNode }): JSX.Element {
  return <div className="ui-card__footer">{children}</div>;
}
