type BrandLogoProps = {
  compact?: boolean;
};

export default function BrandLogo({ compact = false }: BrandLogoProps) {
  return (
    <span className="brand-logo" aria-label="TENNET">
      <img
        className={compact ? "brand-logo__mark" : "brand-logo__wordmark"}
        src={compact ? "/brand/tennet-logo-mark.png" : "/brand/tennet-logo-horizontal.png"}
        alt=""
        aria-hidden="true"
      />
    </span>
  );
}
