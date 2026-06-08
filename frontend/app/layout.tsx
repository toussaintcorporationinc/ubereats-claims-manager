import type { ReactNode } from "react";
import AppLayout from "@/components/AppLayout";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata = {
  title: "TENNET",
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
        <AuthProvider>
          <AppLayout>{children}</AppLayout>
        </AuthProvider>
      </body>
    </html>
  );
}
