"use client";

import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  action?: ReactNode;
};

export default function PremiumEmptyState({ title, description, action }: Props) {
  return (
    <div className="premium-state">
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action ? <div className="actions">{action}</div> : null}
    </div>
  );
}
