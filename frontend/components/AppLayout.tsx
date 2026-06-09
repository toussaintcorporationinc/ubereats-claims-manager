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
  { href: "/imports", label: "Imports" },
  { href: "/drafts", label: "Brouillons" },
  { href: "/evidence-tasks", label: "Preuves" },
  { href: "/followups", label: "Relances", ownerOrManagerOnly: true },
  { href: "/customer-refunds", label: "Deductions Uber", ownerOrManagerOnly: true },
  { href: "/recovery", label: "Recuperation", ownerOrManagerOnly: true },
  { href: "/reports", label: "Rapports", ownerOrManagerOnly: true },
  { href: "/uber", label: "Uber", ownerOrManagerOnly: true },
  { href: "/inbox", label: "Reponses Uber", ownerOrManagerOnly: true },
  { href: "/settings/email", label: "Email", ownerOrManagerOnly: true },
  { href: "/users", label: "Utilisateurs", ownerOnly: true },
];

const publicPaths = new Set(["/login", "/setup-owner"]);

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading, logout } = useAuth();
  const isPublicPath = publicPaths.has(pathname) || pathname.startsWith("/evidence-upload/");

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
          <span className="brand-mark">T</span>
          <span>TENNET</span>
        </Link>
        <nav className="nav-list">
          {navigation
            .filter((item) => !item.ownerOnly || user.role === "owner")
            .filter((item) => !item.ownerOrManagerOnly || user.role === "owner" || user.role === "manager")
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
