import Image from "next/image";
import { redirect } from "next/navigation";

import { JobList } from "@/components/job-list";
import { UploadForm } from "@/components/upload-form";
import { getCurrentUser } from "@/lib/auth";
import { parseJobPage } from "@/lib/job-pagination";
import { getJobs } from "@/lib/jobs";

import { logoutAction } from "./actions";


interface HomeProps {
  searchParams: Promise<{ page?: string | string[] }>;
}

/*
THESIS: Meguyomi is a working manga translation desk, not a generic SaaS dashboard.
OWN-WORLD: Cold paper, dense black ink, coral proof marks, screentone, and one original anime translator.
STORY: Upload a Japanese PDF, watch each page move through the desk, then collect the Indonesian edition.
FIRST VIEWPORT: The upload task dominates the left while the translator character anchors a dark proofing panel on the right.
FORM: Asymmetric editorial workspace, selected directly from the user's manga and waifu direction.
*/

export default async function Home({ searchParams }: HomeProps) {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/login");
  }
  const page = parseJobPage((await searchParams).page);
  const jobResult = await getJobs(page);
  const lastPage = Math.max(1, jobResult.pagination.totalPages);
  if (!jobResult.error && page > lastPage) {
    redirect(lastPage === 1 ? "/" : `/?page=${lastPage}`);
  }

  return (
    <div className="min-h-[100dvh]">
      <header className="sticky top-0 z-20 border-b border-[var(--ink)] bg-[var(--surface)]/95 backdrop-blur-sm">
        <div className="mx-auto flex h-[4.5rem] w-full max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span
              aria-hidden="true"
              className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-[var(--ink)] text-lg font-black text-white"
            >
              M
            </span>
            <div className="min-w-0">
              <p className="display-face truncate text-lg leading-none">MEGUYOMI</p>
              <p className="mt-1 truncate text-xs text-[var(--muted)]">
                Manga translation desk
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            <p className="hidden max-w-48 truncate text-sm text-[var(--muted)] sm:block">
              Halo, <strong className="text-[var(--foreground)]">{user.username}</strong>
            </p>
            <form action={logoutAction}>
              <button
                type="submit"
                className="rounded-[10px] border border-[var(--ink)] bg-transparent px-4 py-2 text-sm font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] active:translate-y-px"
              >
                Keluar
              </button>
            </form>
          </div>
        </div>
      </header>

      <main id="main-content" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-8 lg:py-10">
        <div className="grid overflow-hidden rounded-[14px] border border-[var(--ink)] bg-[var(--surface)] lg:min-h-[38rem] lg:grid-cols-[minmax(0,1.18fr)_minmax(22rem,0.82fr)]">
          <section aria-labelledby="upload-title" className="flex flex-col justify-center p-6 sm:p-10 lg:p-12">
            <p className="mb-5 w-fit rounded-[8px] bg-[var(--accent-wash)] px-3 py-1.5 text-sm font-bold text-[var(--accent-strong)]">
              Jepang ke Indonesia
            </p>
            <h1 id="upload-title" className="display-face max-w-[13ch] text-4xl leading-[1.03] sm:text-5xl lg:text-6xl">
              Satu PDF masuk. Ceritanya terbaca.
            </h1>
            <p className="mt-5 max-w-[52ch] text-base leading-7 text-[var(--muted)] sm:text-lg">
              Unggah manga Jepang, mulai terjemahan saat siap, lalu ambil PDF bahasa Indonesia.
            </p>
            <UploadForm />
          </section>

          <aside className="relative min-h-[28rem] overflow-hidden bg-[var(--ink)] text-white lg:min-h-full">
            <div className="halftone absolute inset-0 opacity-70" aria-hidden="true" />
            <div className="absolute -right-20 -top-24 size-80 rounded-full bg-[var(--accent)]" aria-hidden="true" />
            <div className="absolute inset-x-6 top-6 z-10 max-w-52 rounded-[10px] bg-white p-4 text-[var(--ink)] sm:inset-x-auto sm:left-8">
              <p className="font-bold">Bekerja per halaman</p>
              <p className="mt-1 text-sm leading-5 text-[var(--muted)]">
                Checkpoint menjaga progres saat layanan perlu mencoba ulang.
              </p>
            </div>
            <div className="absolute -bottom-24 left-1/2 -translate-x-1/2 sm:-bottom-24 lg:-bottom-20">
              <Image
                src="/meguyomi-translator.png"
                alt="Ilustrasi penerjemah manga Meguyomi membawa halaman manga"
                width={1024}
                height={1536}
                priority
                className="mascot-float h-[35rem] w-auto max-w-none object-contain sm:h-[42rem] lg:h-[46rem]"
              />
            </div>
            <div className="absolute bottom-5 left-5 z-10 rounded-[8px] bg-[var(--accent)] px-3 py-2 text-sm font-bold sm:left-8">
              PDF tetap privat di server
            </div>
          </aside>
        </div>

        <section
          aria-labelledby="jobs-title"
          className="mt-8 rounded-[14px] border border-[var(--ink)] bg-[var(--surface)] p-5 sm:p-8 lg:mt-10 lg:p-10"
        >
          <div className="flex flex-col gap-3 border-b border-[var(--border)] pb-6 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="jobs-title" className="display-face text-3xl sm:text-4xl">
                Meja pekerjaan
              </h2>
              <p className="mt-2 max-w-xl leading-6 text-[var(--muted)]">
                Pantau persiapan, retry, terjemahan, dan PDF yang siap diunduh.
              </p>
            </div>
            <p className="w-fit rounded-[8px] bg-[var(--ink)] px-3 py-2 text-sm font-bold tabular-nums text-white">
              {jobResult.pagination.totalItems} PDF
            </p>
          </div>
          <JobList
            jobs={jobResult.jobs}
            pagination={jobResult.pagination}
            error={jobResult.error}
          />
        </section>
      </main>
    </div>
  );
}
