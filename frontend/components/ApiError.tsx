"use client";

import Link from "next/link";
import { ApiError as ApiErrorModel, SESSION_EXPIRED_MESSAGE } from "@/lib/api";

export default function ApiError({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  const message = error instanceof Error ? error.message : "Erreur API";
  const status = error instanceof ApiErrorModel ? error.status : null;
  const detail = error instanceof ApiErrorModel ? error.detail : null;
  const isUnauthorized = status === 401;

  return (
    <div className="api-error" role="alert">
      <strong>{status ? `Erreur ${status}` : "Erreur"}</strong>
      <span>{isUnauthorized ? SESSION_EXPIRED_MESSAGE : message}</span>
      {isUnauthorized ? (
        <Link href="/login" className="secondary-button">
          Se reconnecter
        </Link>
      ) : null}
      {!isUnauthorized && detail && typeof detail === "object" ? <pre>{JSON.stringify(detail, null, 2)}</pre> : null}
    </div>
  );
}
