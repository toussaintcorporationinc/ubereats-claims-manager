export default function LoadingState({ label = "Chargement" }: { label?: string }) {
  return <div className="loading-state">{label}</div>;
}
