"use client";

import Link from "next/link";
import BrandLogo from "@/components/BrandLogo";
import type { UserRole } from "@/lib/api";

export type NavItem = {
  href: string;
  label: string;
  ownerOnly?: boolean;
  ownerOrManagerOnly?: boolean;
};

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
        <nav className="nav-list">
          {visibleItems.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link" onClick={onClose}>
              {item.label}
            </Link>
          ))}
        </nav>
        <button type="button" className="secondary-button" onClick={onLogout}>
          Deconnexion
        </button>
      </aside>
    </div>
  );
}
