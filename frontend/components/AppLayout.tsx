"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import BrandLogo from "@/components/BrandLogo";
import LoadingState from "@/components/LoadingState";
import MobileHeader from "@/components/MobileHeader";
import MobileNavDrawer, { type NavItem } from "@/components/MobileNavDrawer";
import { useAuth } from "@/lib/auth";

const navigation: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/smart-import", label: "Smart Import", ownerOrManagerOnly: true },
  { href: "/restaurants", label: "Restaurants" },
  { href: "/orders", label: "Commandes" },
  { href: "/imports", label: "Imports" },
  { href: "/drafts", label: "Brouillons" },
  { href: "/evidence-tasks", label: "Preuves" },
  { href: "/live-evidence", label: "Station preuves" },
  { href: "/evidence-imports", label: "Import preuves", ownerOrManagerOnly: true },
  { href: "/followups", label: "Relances", ownerOrManagerOnly: true },
  { href: "/appeals", label: "Appels / Refus Uber", ownerOrManagerOnly: true },
  { href: "/autopilot", label: "AutoPilot", ownerOrManagerOnly: true },
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
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

  const handleLogout = () => {
    setMobileMenuOpen(false);
    logout();
    router.replace("/login");
  };

  return (
    <div className="app-shell">
      <MobileHeader onMenuClick={() => setMobileMenuOpen(true)} />
      <MobileNavDrawer
        open={mobileMenuOpen}
        items={navigation}
        userRole={user.role}
        onClose={() => setMobileMenuOpen(false)}
        onLogout={handleLogout}
      />
      <aside className="sidebar" aria-label="Navigation principale">
        <Link href="/dashboard" className="brand">
          <BrandLogo />
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
            onClick={handleLogout}
          >
            Deconnexion
          </button>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
