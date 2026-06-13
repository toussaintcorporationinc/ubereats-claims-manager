export default function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="empty-state">
      <div>{title}</div>
      {description ? <p className="muted">{description}</p> : null}
    </div>
  );
}
