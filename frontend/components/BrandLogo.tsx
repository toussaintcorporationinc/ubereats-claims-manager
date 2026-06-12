type BrandLogoProps = {
  compact?: boolean;
};

export default function BrandLogo({ compact = false }: BrandLogoProps) {
  return (
    <span className="brand-logo" aria-label="TENNET">
      <img className="brand-logo__mark" src="/brand-mark.svg" alt="" aria-hidden="true" />
      {compact ? null : <span className="brand-logo__word">TENNET</span>}
    </span>
  );
}
