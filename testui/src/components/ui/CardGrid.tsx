/**
 * Grid wrapper that enforces equal-width AND equal-height cards in a row --
 * the direct, mechanical fix for "boxes should be even sized": CSS grid
 * with align-items:stretch, paired with Card's own height:100%, instead of
 * a flex/inline layout that sizes each box to its own content.
 */

import type { CSSProperties, ReactNode } from "react";

export interface CardGridProps {
  children: ReactNode;
  /** Minimum column width before wrapping to a new row. */
  minWidth?: number;
}

export function CardGrid({ children, minWidth = 260 }: CardGridProps): JSX.Element {
  const style = { "--ui-card-grid-min": `${minWidth}px` } as CSSProperties;
  return (
    <div className="ui-card-grid" style={style}>
      {children}
    </div>
  );
}
