"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import {
  getJobStatusPresentation,
  shouldRefreshJobStatus,
} from "@/lib/job-status";
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
  const hasActiveJobs = jobs.some((job) => shouldRefreshJobStatus(job.status));

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
          </li>
        );
      })}
    </ol>
  );
}
