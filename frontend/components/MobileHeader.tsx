"use client";

import Link from "next/link";

type Props = {
  title?: string;
  onMenuClick: () => void;
};

export default function MobileHeader({ title = "TENNET", onMenuClick }: Props) {
  return (
    <header className="mobile-header">
      <button type="button" className="icon-button" aria-label="Ouvrir le menu" onClick={onMenuClick}>
        Menu
      </button>
      <Link href="/dashboard" className="mobile-header__brand">
        <span className="brand-mark">T</span>
        <span>{title}</span>
      </Link>
      <Link href="/smart-import" className="secondary-button mobile-header__quick">
        Import
      </Link>
    </header>
  );
}
