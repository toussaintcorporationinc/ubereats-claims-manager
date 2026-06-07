import Link from "next/link";
import type { ReactNode } from "react";

const navigation = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/restaurants", label: "Restaurants" },
  { href: "/orders", label: "Commandes" },
  { href: "/drafts", label: "Brouillons" },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navigation principale">
        <Link href="/dashboard" className="brand">
          <span className="brand-mark">CM</span>
          <span>Claims Manager</span>
        </Link>
        <nav className="nav-list">
          {navigation.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
