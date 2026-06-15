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
  { href: "/dashboard", label: "A faire", group: "main" },
  { href: "/smart-import", label: "Deposer fichiers", group: "main", ownerOrManagerOnly: true },
  { href: "/remboursements", label: "Remboursements", group: "main", ownerOrManagerOnly: true },
  { href: "/annulations", label: "Annulations", group: "main", ownerOrManagerOnly: true },
  { href: "/evidence-tasks", label: "Preuves", group: "main" },
  { href: "/live-evidence", label: "Camera + tickets", group: "main" },
  { href: "/recovery", label: "Recuperation", group: "main", ownerOrManagerOnly: true },
  { href: "/restaurants", label: "Restaurants", group: "work", ownerOrManagerOnly: true },
  { href: "/orders", label: "Dossiers", group: "work", ownerOrManagerOnly: true },
  { href: "/uber", label: "Imports Uber", group: "work", ownerOrManagerOnly: true },
  { href: "/evidence-imports", label: "Import preuves", group: "work", ownerOrManagerOnly: true },
  { href: "/drafts", label: "Brouillons", group: "follow", ownerOrManagerOnly: true },
  { href: "/followups", label: "Relances", group: "follow", ownerOrManagerOnly: true },
  { href: "/appeals", label: "Appels / Refus", group: "follow", ownerOrManagerOnly: true },
  { href: "/customer-refunds", label: "Dossiers remboursements", group: "follow", ownerOrManagerOnly: true },
  { href: "/inbox", label: "Reponses Uber", group: "follow", ownerOrManagerOnly: true },
  { href: "/autopilot", label: "AutoPilot", group: "admin", ownerOrManagerOnly: true },
  { href: "/reports", label: "Rapports", group: "admin", ownerOrManagerOnly: true },
  { href: "/settings/email", label: "Email", group: "admin", ownerOrManagerOnly: true },
  { href: "/users", label: "Utilisateurs", group: "admin", ownerOnly: true },
];

const navGroups: Array<{ key: NavItem["group"]; label: string }> = [
  { key: "main", label: "Essentiel" },
  { key: "work", label: "Dossiers" },
  { key: "follow", label: "Suivi" },
  { key: "admin", label: "Pilotage" },
];

const primaryNavigationHrefs = new Set([
  "/dashboard",
  "/remboursements",
  "/annulations",
  "/evidence-tasks",
  "/live-evidence",
  "/restaurants",
]);

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
  const visibleNavigation = navigation.filter((item) => canSeeNavItem(item, user.role));
  const primaryNavigation = visibleNavigation.filter((item) => primaryNavigationHrefs.has(item.href));
  const advancedNavigation = visibleNavigation.filter((item) => !primaryNavigationHrefs.has(item.href));

  return (
    <div className="app-shell">
      <MobileHeader onMenuClick={() => setMobileMenuOpen(true)} />
      <MobileNavDrawer
        open={mobileMenuOpen}
        items={visibleNavigation}
        userRole={user.role}
        onClose={() => setMobileMenuOpen(false)}
        onLogout={handleLogout}
      />
      <aside className="sidebar" aria-label="Navigation principale">
        <Link href="/dashboard" className="brand">
          <BrandLogo />
        </Link>
        <nav className="nav-list nav-list--grouped">
          <div className="nav-section">
            <span className="nav-section-title">Essentiel</span>
            {primaryNavigation.map((item) => (
              <Link key={item.href} href={item.href} className="nav-link">
                {item.label}
              </Link>
            ))}
          </div>
          {advancedNavigation.length > 0 ? (
            <details className="nav-advanced">
              <summary>Outils avances</summary>
              {navGroups.map((group) => {
                const groupItems = advancedNavigation.filter((item) => item.group === group.key);

                if (groupItems.length === 0) {
                  return null;
                }

                return (
                  <div key={group.key} className="nav-section">
                    <span className="nav-section-title">{group.label}</span>
                    {groupItems.map((item) => (
                      <Link key={item.href} href={item.href} className="nav-link">
                        {item.label}
                      </Link>
                    ))}
                  </div>
                );
              })}
            </details>
          ) : null}
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

function canSeeNavItem(item: NavItem, role: string): boolean {
  if (item.ownerOnly && role !== "owner") {
    return false;
  }
  if (item.ownerOrManagerOnly && role !== "owner" && role !== "manager") {
    return false;
  }
  return true;
}
