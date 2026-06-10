"use client";

import ApiError from "@/components/ApiError";

export default function PremiumErrorState({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  return (
    <div className="premium-state premium-state--error">
      <strong>Action impossible pour le moment</strong>
      <ApiError error={error} />
    </div>
  );
}
