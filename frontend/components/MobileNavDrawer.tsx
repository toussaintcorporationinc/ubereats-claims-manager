"use client";

import Link from "next/link";
import BrandLogo from "@/components/BrandLogo";
import type { UserRole } from "@/lib/api";

export type NavItem = {
  href: string;
  label: string;
  group: "main" | "work" | "follow" | "admin";
  ownerOnly?: boolean;
  ownerOrManagerOnly?: boolean;
};

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

type Props = {
  open: boolean;
  items: NavItem[];
  userRole: UserRole;
  onClose: () => void;
  onLogout: () => void;
};

export default function MobileNavDrawer({ open, items, userRole, onClose, onLogout }: Props) {
  const visibleItems = items
    .filter((item) => !item.ownerOnly || userRole === "owner")
    .filter((item) => !item.ownerOrManagerOnly || userRole === "owner" || userRole === "manager");
  const primaryItems = visibleItems.filter((item) => primaryNavigationHrefs.has(item.href));
  const advancedItems = visibleItems.filter((item) => !primaryNavigationHrefs.has(item.href));

  return (
    <div className={`mobile-nav ${open ? "mobile-nav--open" : ""}`} aria-hidden={!open}>
      <button type="button" className="mobile-nav__backdrop" aria-label="Fermer le menu" onClick={onClose} />
      <aside className="mobile-nav__drawer" aria-label="Navigation mobile">
        <div className="mobile-nav__top">
          <Link href="/dashboard" className="brand" onClick={onClose}>
            <BrandLogo />
          </Link>
          <button type="button" className="icon-button" aria-label="Fermer le menu" onClick={onClose}>
            x
          </button>
        </div>
        <nav className="nav-list nav-list--grouped">
          <div className="nav-section">
            <span className="nav-section-title">Essentiel</span>
            {primaryItems.map((item) => (
              <Link key={item.href} href={item.href} className="nav-link" onClick={onClose}>
                {item.label}
              </Link>
            ))}
          </div>
          {advancedItems.length > 0 ? (
            <details className="nav-advanced">
              <summary>Outils avances</summary>
              {navGroups.map((group) => {
                const groupItems = advancedItems.filter((item) => item.group === group.key);

                if (groupItems.length === 0) {
                  return null;
                }

                return (
                  <div key={group.key} className="nav-section">
                    <span className="nav-section-title">{group.label}</span>
                    {groupItems.map((item) => (
                      <Link key={item.href} href={item.href} className="nav-link" onClick={onClose}>
                        {item.label}
                      </Link>
                    ))}
                  </div>
                );
              })}
            </details>
          ) : null}
        </nav>
        <button type="button" className="secondary-button" onClick={onLogout}>
          Deconnexion
        </button>
      </aside>
    </div>
  );
}
