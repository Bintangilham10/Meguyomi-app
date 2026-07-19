import { redirect } from "next/navigation";

import { JobList } from "@/components/job-list";
import { UploadForm } from "@/components/upload-form";
import { getCurrentUser } from "@/lib/auth";
import { getJobs } from "@/lib/jobs";

import { logoutAction } from "./actions";


export default async function Home() {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/login");
  }
  const jobResult = await getJobs();

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4 lg:px-10">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
              Meguyomi
            </p>
            <p className="mt-1 text-sm text-[var(--muted)]">Workspace milik {user.username}</p>
          </div>
          <form action={logoutAction}>
            <button
              type="submit"
              className="border border-[var(--border)] px-4 py-2 text-sm font-semibold transition hover:border-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              Keluar
            </button>
          </form>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 py-10 lg:px-10 lg:py-14">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
            Dashboard
          </p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            Terjemahkan manga Jepang dari satu PDF.
          </h1>
          <p className="mt-5 text-lg leading-8 text-[var(--muted)]">
            Unggah bab manga untuk diperiksa dan dimasukkan ke antrean terjemahan bahasa Indonesia.
          </p>
        </div>

        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(22rem,0.95fr)] lg:items-start">
          <section aria-labelledby="upload-title" className="border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Langkah 01</p>
            <h2 id="upload-title" className="mt-2 text-2xl font-semibold">Upload manga</h2>
            <p className="mt-3 leading-7 text-[var(--muted)]">
              Setelah upload, worker menyiapkan halaman. Anda dapat memulai AI saat siap menggunakan kuota Gemini.
            </p>
            <UploadForm />
          </section>

          <section aria-labelledby="jobs-title" className="border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-8">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Langkah 02</p>
                <h2 id="jobs-title" className="mt-2 text-2xl font-semibold">Riwayat pekerjaan</h2>
              </div>
              <p className="text-sm tabular-nums text-[var(--muted)]">{jobResult.jobs.length} PDF</p>
            </div>
            <JobList jobs={jobResult.jobs} error={jobResult.error} />
          </section>
        </div>
      </main>
    </div>
  );
}
