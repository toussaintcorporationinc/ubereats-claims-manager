type StatCardProps = {
  label: string;
  value: string | number;
  detail?: string;
};

export default function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <article className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <p>{detail}</p> : null}
    </article>
  );
}
