"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";
import LoadingState from "@/components/LoadingState";
import { useAuth } from "@/lib/auth";

const navigation = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/restaurants", label: "Restaurants" },
  { href: "/orders", label: "Commandes" },
  { href: "/drafts", label: "Brouillons" },
  { href: "/users", label: "Utilisateurs", ownerOnly: true },
];

const publicPaths = new Set(["/login", "/setup-owner"]);

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading, logout } = useAuth();
  const isPublicPath = publicPaths.has(pathname);

  useEffect(() => {
    if (!loading && !user && !isPublicPath) {
      router.replace("/login");
    }
  }, [isPublicPath, loading, router, user]);

  if (isPublicPath) {
    return <main className="auth-content">{children}</main>;
  }

  if (loading || !user) {
    return (
      <main className="main-content">
        <LoadingState label="Verification de la session" />
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navigation principale">
        <Link href="/dashboard" className="brand">
          <span className="brand-mark">CM</span>
          <span>Claims Manager</span>
        </Link>
        <nav className="nav-list">
          {navigation
            .filter((item) => !item.ownerOnly || user.role === "owner")
            .map((item) => (
              <Link key={item.href} href={item.href} className="nav-link">
                {item.label}
              </Link>
            ))}
        </nav>
        <div className="user-card">
          <span>{user.full_name ?? user.email}</span>
          <strong>{user.role}</strong>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
          >
            Deconnexion
          </button>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
