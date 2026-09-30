"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { JobListItem } from "@/components/job-list-item";
import { JobPagination } from "@/components/job-pagination";
import { StudioIcon } from "@/components/studio-icon";
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
  const [stoppingJobId, setStoppingJobId] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewAfterStopJobId, setPreviewAfterStopJobId] = useState<
    string | null
  >(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const hasActiveJobs = jobs.some((job) => shouldRefreshJobStatus(job.status));
  const stoppedJobReadyForPreview = previewAfterStopJobId
    ? jobs.some(
        (job) =>
          job.id === previewAfterStopJobId &&
          job.status === "TRANSLATION_STOPPED" &&
          job.resultAvailable,
      )
    : false;
  const openPreviewJobId =
    previewJobId ??
    (stoppedJobReadyForPreview ? previewAfterStopJobId : null);

  function toggleResultPreview(jobId: string) {
    const isOpen = openPreviewJobId === jobId;
    setPreviewAfterStopJobId(null);
    setPreviewJobId(isOpen ? null : jobId);
  }

  async function startTranslation(jobId: string) {
    setStartingJobId(jobId);
    setPreviewJobId((current) => (current === jobId ? null : current));
    setPreviewAfterStopJobId((current) =>
      current === jobId ? null : current,
    );
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
      const job = parseJobResponse(body);
      if (!job) {
        setActionError("Respons pekerjaan terjemahan tidak valid.");
        return;
      }
      if (job.status === "FAILED" && job.failureCode === "QUEUE_UNAVAILABLE") {
        setActionError(
          "Antrean kerja masih tidak tersedia. Periksa layanan Redis lalu coba lagi.",
        );
      }
      router.refresh();
    } catch {
      setActionError("Layanan terjemahan AI sedang tidak tersedia.");
    } finally {
      setStartingJobId(null);
    }
  }

  async function stopTranslation(jobId: string) {
    setStoppingJobId(jobId);
    setActionError(null);
    try {
      const response = await fetch(`/api/jobs/${jobId}/translation/stop`, {
        method: "POST",
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setActionError(
          parseApiErrorMessage(body, "Terjemahan belum dapat dihentikan."),
        );
        return;
      }
      const job = parseJobResponse(body);
      if (
        !job ||
        (job.status !== "TRANSLATION_STOPPING" &&
          job.status !== "TRANSLATION_STOPPED")
      ) {
        setActionError("Respons penghentian terjemahan tidak valid.");
        return;
      }
      setPreviewJobId(null);
      setPreviewAfterStopJobId(jobId);
      router.refresh();
    } catch {
      setActionError("Layanan penghentian terjemahan sedang tidak tersedia.");
    } finally {
      setStoppingJobId(null);
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
      const job = parseJobResponse(body);
      if (!job) {
        setActionError("Respons pekerjaan terjemahan tidak valid.");
        return;
      }
      if (job.status === "FAILED" && job.failureCode === "QUEUE_UNAVAILABLE") {
        setActionError(
          "Antrean kerja masih tidak tersedia. Periksa layanan Redis lalu coba lagi.",
        );
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
      setPreviewJobId((current) => (current === job.id ? null : current));
      setPreviewAfterStopJobId((current) =>
        current === job.id ? null : current,
      );
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
      <div role="alert" className="mt-6 rounded-[14px] bg-[var(--accent-wash)] p-5 text-[var(--accent-strong)]">
        <p className="font-bold">Antrean studio belum dapat dibuka</p>
        <p className="mt-1 text-sm leading-6">{error}</p>
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div role="status" className="queue-empty">
        <span className="empty-illustration" aria-hidden="true"><StudioIcon name="book" /><span>01</span></span>
        <div><p className="display-face text-2xl">Chapter pertamamu menunggu.</p>
        <p className="mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">Unggah PDF di panel atas. Progres dan hasil terjemahannya akan muncul di sini.</p></div>
      </div>
    );
  }

  return (
    <>
      {actionError ? (
        <p role="alert" className="mt-5 rounded-[10px] bg-[var(--accent-wash)] px-4 py-3 text-sm font-medium text-[var(--danger)]">
          {actionError}
        </p>
      ) : null}
      <ol
        aria-live="polite"
        className="queue-list"
      >
        {jobs.map((job) => (
          <JobListItem
            key={job.id}
            job={job}
            isDeleting={deletingJobId === job.id}
            isStarting={startingJobId === job.id}
            isStopping={stoppingJobId === job.id}
            isPreviewOpen={openPreviewJobId === job.id}
            onDelete={deleteJob}
            onTogglePreview={toggleResultPreview}
            onStartTranslation={startTranslation}
            onStopTranslation={stopTranslation}
            onRetryPreparation={retryPreparation}
          />
        ))}
      </ol>
      <JobPagination pagination={pagination} />
    </>
  );
}
