import type { ReactNode } from "react";
import { Outfit, Public_Sans, Urbanist } from "next/font/google";
import AppLayout from "@/components/AppLayout";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const headingFont = Public_Sans({
  subsets: ["latin"],
  variable: "--font-heading",
  display: "swap",
});

const bodyFont = Outfit({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

const mobileFont = Urbanist({
  subsets: ["latin"],
  variable: "--font-mobile",
  display: "swap",
});

export const metadata = {
  title: "TENNET",
  description: "Interface de gestion des reclamations Uber Eats.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/icons/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icons/favicon-16.png", sizes: "16x16", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
    apple: "/icons/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="fr" className={`${headingFont.variable} ${bodyFont.variable} ${mobileFont.variable}`}>
      <body>
        <AuthProvider>
          <AppLayout>{children}</AppLayout>
        </AuthProvider>
      </body>
    </html>
  );
}
