"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type User } from "@/lib/api";

export default function UsersPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getUsers()
      .then(setUsers)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (user?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  if (loading) {
    return <LoadingState label="Chargement des utilisateurs" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Utilisateurs</p>
          <h1>Utilisateurs</h1>
        </div>
        <Link href="/users/new" className="button">
          Creer utilisateur
        </Link>
      </div>

      <ApiError error={error} />

      {users.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Nom</th>
                <th>Role</th>
                <th>Statut</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => (
                <tr key={item.id}>
                  <td>{item.email}</td>
                  <td>{item.full_name ?? "-"}</td>
                  <td>{item.role}</td>
                  <td>
                    <StatusBadge status={item.active ? "active" : "inactive"} />
                  </td>
                  <td>
                    <Link href={`/users/${item.id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun utilisateur" />
      )}
    </section>
  );
}
