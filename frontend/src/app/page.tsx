import { redirect } from "next/navigation";
import { CharacterStage } from "@/components/character-stage";
import { EngineStatus } from "@/components/engine-status";
import { JobList } from "@/components/job-list";
import { StudioHeader, StudioFooter } from "@/components/studio-chrome";
import { StudioIcon } from "@/components/studio-icon";
import { UploadForm } from "@/components/upload-form";
import { getCurrentUser } from "@/lib/auth";
import { parseJobPage } from "@/lib/job-pagination";
import { getJobs } from "@/lib/jobs";

interface HomeProps {
  searchParams: Promise<{ page?: string | string[] }>;
}

export default async function Home({ searchParams }: HomeProps) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const page = parseJobPage((await searchParams).page);
  const jobResult = await getJobs(page);
  const lastPage = Math.max(1, jobResult.pagination.totalPages);
  if (!jobResult.error && page > lastPage) {
    redirect(lastPage === 1 ? "/" : `/?page=${lastPage}`);
  }
  const totalJobs = jobResult.error
    ? "--"
    : jobResult.pagination.totalItems.toString().padStart(2, "0");

  return (
    <div className="app-shell">
      <StudioHeader username={user.username} />
      <main id="main-content" className="studio-main">
        <section className="hero-stage" aria-labelledby="studio-title">
          <div className="hero-copy">
            <p className="hero-kicker">
              <span className="kicker-line" /> DARI PANEL, JADI CERITA.
            </p>
            <h1 id="studio-title" className="hero-title">
              Manga favorit.
              <br />
              <span>
                Bahasa kita<em>.</em>
              </span>
            </h1>
            <p className="hero-lead">
              Bawa manga Jepang dan manhua Mandarin ke bahasa Indonesia. Satu
              PDF, satu studio lokal, lebih banyak cerita.
            </p>
            <div className="hero-tags">
              <span>
                JP / ZH <StudioIcon name="arrow" /> ID
              </span>
              <span>LOKAL. TANPA API KEY.</span>
            </div>
            <UploadForm />
          </div>
          <CharacterStage />
        </section>
        <section className="signal-strip" aria-label="Informasi studio">
          <EngineStatus />
          <div className="signal-card">
            <span className="signal-number">{totalJobs}</span>
            <span>
              <strong>PDF di studio</strong>
              <small>Setiap chapter punya ceritanya.</small>
            </span>
          </div>
          <div className="signal-card">
            <span className="signal-icon signal-icon-cyan">
              <StudioIcon name="book" />
            </span>
            <span>
              <strong>Jepang & Mandarin</strong>
              <small>Pilih bahasa atau deteksi otomatis.</small>
            </span>
          </div>
        </section>
        <section
          id="antrean"
          className="queue-section"
          aria-labelledby="queue-title"
        >
          <div className="queue-header">
            <div>
              <p className="section-kicker">02 / YOUR CHAPTERS</p>
              <h2 id="queue-title">
                Antrean studio<span>.</span>
              </h2>
              <p>
                Dari halaman pertama sampai siap dibaca. Semua progres ada di
                sini.
              </p>
            </div>
            <span className="queue-counter">
              {totalJobs} <small>PDF</small>
            </span>
          </div>
          <JobList
            jobs={jobResult.jobs}
            pagination={jobResult.pagination}
            error={jobResult.error}
          />
        </section>
      </main>
      <StudioFooter />
    </div>
  );
}
