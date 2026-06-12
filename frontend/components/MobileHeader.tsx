"use client";

import Link from "next/link";
import BrandLogo from "@/components/BrandLogo";

type Props = {
  title?: string;
  onMenuClick: () => void;
};

export default function MobileHeader({ onMenuClick }: Props) {
  return (
    <header className="mobile-header">
      <button type="button" className="icon-button" aria-label="Ouvrir le menu" onClick={onMenuClick}>
        Menu
      </button>
      <Link href="/dashboard" className="mobile-header__brand">
        <BrandLogo />
      </Link>
      <Link href="/smart-import" className="secondary-button mobile-header__quick">
        Import
      </Link>
    </header>
  );
}
