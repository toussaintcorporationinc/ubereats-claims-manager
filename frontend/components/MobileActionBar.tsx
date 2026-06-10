"use client";

import type { ReactNode } from "react";

export default function MobileActionBar({ children }: { children: ReactNode }) {
  return <div className="mobile-action-bar">{children}</div>;
}
