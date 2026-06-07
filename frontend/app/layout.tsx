import type { ReactNode } from "react";
import AppLayout from "@/components/AppLayout";
import "./globals.css";

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
        <AppLayout>{children}</AppLayout>
      </body>
    </html>
  );
}
