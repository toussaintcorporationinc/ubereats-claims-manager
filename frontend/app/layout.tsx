import type { ReactNode } from "react";
import "./globals.css";

const navigation = [
  { href: "/", label: "Accueil" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/restaurants", label: "Restaurants" },
  { href: "/orders", label: "Commandes" },
];

export const metadata = {
  title: "Uber Eats Claims Manager",
  description: "Interface de gestion des reclamations Uber Eats.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="fr">
      <body>
        <div className="app-shell">
          <aside className="sidebar" aria-label="Navigation principale">
            <a href="/" className="brand">
              <span className="brand-mark">CM</span>
              <span>Claims Manager</span>
            </a>
            <nav className="nav-list">
              {navigation.map((item) => (
                <a key={item.href} href={item.href} className="nav-link">
                  {item.label}
                </a>
              ))}
            </nav>
          </aside>
          <main className="main-content">{children}</main>
        </div>
      </body>
    </html>
  );
}
