const services = [
  { name: "Web", detail: "Next.js App Router" },
  { name: "API", detail: "FastAPI" },
  { name: "Worker", detail: "Celery + Redis" },
  { name: "Data", detail: "PostgreSQL" },
];


export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col justify-center px-6 py-16 lg:px-10">
      <p className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
        Meguyomi MVP
      </p>
      <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">
        Fondasi penerjemah manga sudah siap.
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--muted)]">
        Scaffold aplikasi telah terhubung untuk pengembangan alur upload PDF,
        terjemahan Jepang–Indonesia, pratinjau, dan unduhan hasil.
      </p>

      <section className="mt-12 border-t border-[var(--border)] pt-8" aria-labelledby="services-heading">
        <h2 id="services-heading" className="text-sm font-semibold uppercase tracking-wider">
          Layanan dasar
        </h2>
        <dl className="mt-5 grid gap-px overflow-hidden border border-[var(--border)] bg-[var(--border)] sm:grid-cols-2 lg:grid-cols-4">
          {services.map((service) => (
            <div key={service.name} className="bg-[var(--surface)] p-5">
              <dt className="font-semibold">{service.name}</dt>
              <dd className="mt-1 text-sm text-[var(--muted)]">{service.detail}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}
