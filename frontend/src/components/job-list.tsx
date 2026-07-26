"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { JobListItem } from "@/components/job-list-item";
import { JobPagination } from "@/components/job-pagination";
import { parseApiErrorMessage, parseJobResponse } from "@/lib/job-contract";
import { shouldRefreshJobStatus } from "@/lib/job-status";
import type { JobPagination as JobPaginationData, TranslationJob } from "@/types/job";


interface JobListProps {
  jobs: TranslationJob[];
  pagination: JobPaginationData;
  error: string | null;
}


export function JobList({ jobs, pagination, error }: JobListProps) {
  const router = useRouter();
  const [startingJobId, setStartingJobId] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
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

  async function retryPreparation(jobId: string) {
    setStartingJobId(jobId);
    setActionError(null);
    try {
      const response = await fetch(`/api/jobs/${jobId}/preparation`, {
        method: "POST",
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setActionError(
          parseApiErrorMessage(body, "Persiapan ulang tidak dapat dimulai."),
        );
        return;
      }
      if (!parseJobResponse(body)) {
        setActionError("Respons pekerjaan terjemahan tidak valid.");
        return;
      }
      router.refresh();
    } catch {
      setActionError("Layanan persiapan sedang tidak tersedia.");
    } finally {
      setStartingJobId(null);
    }
  }

  async function deleteJob(job: TranslationJob) {
    const confirmed = window.confirm(
      `Hapus ${job.originalFilename} beserta seluruh file hasilnya?`,
    );
    if (!confirmed) {
      return;
    }

    setDeletingJobId(job.id);
    setActionError(null);
    try {
      const response = await fetch(`/api/jobs/${job.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const body: unknown = await response.json().catch(() => null);
        setActionError(
          parseApiErrorMessage(body, "Pekerjaan belum dapat dihapus."),
        );
        return;
      }
      router.refresh();
    } catch {
      setActionError("Layanan penghapusan sedang tidak tersedia.");
    } finally {
      setDeletingJobId(null);
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
        {jobs.map((job) => (
          <JobListItem
            key={job.id}
            job={job}
            isDeleting={deletingJobId === job.id}
            isStarting={startingJobId === job.id}
            onDelete={deleteJob}
            onStartTranslation={startTranslation}
            onRetryPreparation={retryPreparation}
          />
        ))}
      </ol>
      <JobPagination pagination={pagination} />
    </>
  );
}
