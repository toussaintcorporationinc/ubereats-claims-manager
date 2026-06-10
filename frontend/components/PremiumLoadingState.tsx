"use client";

export default function PremiumLoadingState({ label = "Chargement" }: { label?: string }) {
  return (
    <div className="premium-state premium-state--loading" role="status">
      <strong>{label}</strong>
      <span className="premium-loader" aria-hidden="true" />
    </div>
  );
}
