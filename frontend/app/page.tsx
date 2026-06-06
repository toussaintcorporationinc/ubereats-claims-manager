const overview = [
  { label: "Reclamations", value: "0", detail: "En attente de connexion" },
  { label: "Restaurants", value: "0", detail: "A synchroniser" },
  { label: "Commandes", value: "0", detail: "A synchroniser" },
];

export default function HomePage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <p className="eyebrow">V1 technique</p>
        <h1>Uber Eats Claims Manager</h1>
      </div>

      <div className="overview-grid" aria-label="Apercu">
        {overview.map((item) => (
          <article className="metric-card" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

