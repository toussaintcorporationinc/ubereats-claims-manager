"use client";

import type { ReactNode } from "react";

type Props<T> = {
  items: T[];
  desktop: ReactNode;
  renderMobileCard: (item: T) => ReactNode;
  empty?: ReactNode;
};

export default function ResponsiveDataList<T>({ items, desktop, renderMobileCard, empty = null }: Props<T>) {
  if (items.length === 0) {
    return <>{empty}</>;
  }

  return (
    <>
      <div className="desktop-data">{desktop}</div>
      <div className="mobile-card-list">{items.map(renderMobileCard)}</div>
    </>
  );
}
