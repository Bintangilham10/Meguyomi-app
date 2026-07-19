"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getJobStatusPresentation,
  shouldRefreshJobStatus,
} from "@/lib/job-status";
import { parseApiErrorMessage, parseJobResponse } from "@/lib/job-contract";
import type { TranslationJob } from "@/types/job";


interface JobListProps {
  jobs: TranslationJob[];
  error: string | null;
}


const dateFormatter = new Intl.DateTimeFormat("id-ID", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Jakarta",
});


function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


export function JobList({ jobs, error }: JobListProps) {
  const router = useRouter();
  const [startingJobId, setStartingJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const hasActiveJobs = jobs.some((job) => shouldRefreshJobStatus(job.status));

  async function startTranslation(jobId: string) {
    setStartingJobId(jobId);
    setActionError(null);
    try {
      const response = await fetch(`/api/jobs/${jobId}/translation`, {
        method: "POST",
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setActionError(
          parseApiErrorMessage(body, "Terjemahan AI tidak dapat dimulai."),
        );
        return;
      }
      if (!parseJobResponse(body)) {
        setActionError("Respons pekerjaan terjemahan tidak valid.");
        return;
      }
      router.refresh();
    } catch {
      setActionError("Layanan terjemahan AI sedang tidak tersedia.");
    } finally {
      setStartingJobId(null);
    }
  }

  useEffect(() => {
    if (!hasActiveJobs) {
      return;
    }
    const interval = window.setInterval(() => router.refresh(), 3_000);
    return () => window.clearInterval(interval);
  }, [hasActiveJobs, router]);

  if (error) {
    return (
      <div role="alert" className="mt-6 border border-[var(--danger)] bg-[var(--surface)] p-5">
        <p className="font-semibold">Riwayat belum dapat ditampilkan</p>
        <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{error}</p>
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div role="status" className="mt-6 border border-dashed border-[var(--border-strong)] p-8">
        <p className="font-semibold">Belum ada pekerjaan terjemahan</p>
        <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
          PDF yang berhasil diunggah akan muncul di sini.
        </p>
      </div>
    );
  }

  return (
    <>
      {actionError ? (
        <p role="alert" className="mt-5 text-sm text-[var(--danger)]">
          {actionError}
        </p>
      ) : null}
      <ol
        aria-live="polite"
        className="mt-6 divide-y divide-[var(--border)] border-y border-[var(--border)]"
      >
      {jobs.map((job) => {
        const presentation = getJobStatusPresentation(job.status, job.failureCode);
        const statusClass =
          presentation.tone === "danger"
            ? "border-[var(--danger)] text-[var(--danger)]"
            : "border-[var(--accent-soft)] text-[var(--accent-strong)]";

        return (
          <li
            key={job.id}
            className="grid gap-4 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
          >
            <div className="min-w-0">
              <p className="truncate font-semibold" title={job.originalFilename}>
                {job.originalFilename}
              </p>
              <p className="mt-1 text-sm text-[var(--muted)]">
                {job.pageCount} halaman · {formatBytes(job.sizeBytes)} ·{" "}
                {dateFormatter.format(new Date(job.createdAt))}
              </p>
            </div>
            <div className="flex flex-col items-start gap-2 sm:items-end">
              <p
                className={`inline-flex w-fit items-center gap-2 border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.1em] ${statusClass}`}
              >
                <span
                  className={
                    presentation.tone === "danger"
                      ? "h-2 w-2 bg-[var(--danger)]"
                      : "h-2 w-2 bg-[var(--accent)]"
                  }
                  aria-hidden="true"
                />
                {presentation.label}
                <span className="sr-only">: {presentation.detail}</span>
              </p>
              {job.status === "READY_FOR_TRANSLATION" ? (
                <button
                  type="button"
                  disabled={startingJobId === job.id}
                  onClick={() => startTranslation(job.id)}
                  className="border border-[var(--accent)] px-3 py-2 text-xs font-semibold text-[var(--accent-strong)] transition hover:bg-[var(--accent)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {startingJobId === job.id
                    ? "Mengantrekan..."
                    : "Mulai terjemahan"}
                </button>
              ) : null}
              {job.status === "COMPLETED" && job.resultAvailable ? (
                <a
                  href={`/api/jobs/${job.id}/result`}
                  className="bg-[var(--accent)] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[var(--accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  Download PDF
                </a>
              ) : null}
            </div>
          </li>
        );
      })}
      </ol>
    </>
  );
}
