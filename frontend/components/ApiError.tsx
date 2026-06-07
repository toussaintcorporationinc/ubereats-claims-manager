import { ApiError as ApiErrorModel } from "@/lib/api";

export default function ApiError({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  const message = error instanceof Error ? error.message : "Erreur API";
  const status = error instanceof ApiErrorModel ? error.status : null;
  const detail = error instanceof ApiErrorModel ? error.detail : null;

  return (
    <div className="api-error" role="alert">
      <strong>{status ? `Erreur ${status}` : "Erreur"}</strong>
      <span>{message}</span>
      {detail && typeof detail === "object" ? <pre>{JSON.stringify(detail, null, 2)}</pre> : null}
    </div>
  );
}
