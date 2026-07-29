import { canDeleteJob } from "@/lib/job-deletion";
import {
  getJobStatusPresentation,
  shouldShowTranslationProgress,
} from "@/lib/job-status";
import type { TranslationJob } from "@/types/job";


interface JobListItemProps {
  job: TranslationJob;
  isDeleting: boolean;
  isStarting: boolean;
  onDelete: (job: TranslationJob) => void;
  onStartTranslation: (jobId: string) => void;
  onRetryPreparation: (jobId: string) => void;
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


export function JobListItem({
  job,
  isDeleting,
  isStarting,
  onDelete,
  onStartTranslation,
  onRetryPreparation,
}: JobListItemProps) {
  const presentation = getJobStatusPresentation(
    job.status,
    job.failureCode,
    job.translationWaitReason,
  );
  const canStartTranslation =
    job.status === "READY_FOR_TRANSLATION" || job.canRetryTranslation;
  const statusClass =
    presentation.tone === "danger"
      ? "bg-[var(--accent-wash)] text-[var(--danger)]"
      : "bg-[var(--background)] text-[var(--foreground)]";

  return (
    <li className="grid gap-5 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,auto)] lg:items-center">
      <div className="min-w-0">
        <p className="truncate text-lg font-bold" title={job.originalFilename}>
          {job.originalFilename}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--muted)]">
          <span>{job.pageCount} halaman</span>
          <span>{formatBytes(job.sizeBytes)}</span>
          <span>{dateFormatter.format(new Date(job.createdAt))}</span>
        </div>
        {shouldShowTranslationProgress(job.status, job.translatedPageCount) ? (
          <div className="mt-4 max-w-md">
            <div className="flex justify-between gap-4 text-xs text-[var(--muted)]">
              <span>
                {job.status === "FAILED"
                  ? "Checkpoint tersimpan"
                  : job.status === "TRANSLATION_RETRY_WAIT"
                    ? "Checkpoint tersimpan"
                  : job.status === "TRANSLATION_QUEUED"
                    ? "Akan dilanjutkan"
                    : "Progres terjemahan"}
              </span>
              <span>
                {job.translatedPageCount}/{job.pageCount} halaman
              </span>
            </div>
            <progress
              aria-label={`Terjemahan ${job.originalFilename}`}
              className="job-progress mt-2 h-2 w-full"
              max={job.pageCount}
              value={job.translatedPageCount}
            />
          </div>
        ) : null}
      </div>
      <div className="flex flex-col items-start gap-3 lg:items-end">
        <p
          className={`inline-flex w-fit rounded-[8px] px-3 py-2 text-xs font-bold ${statusClass}`}
        >
          {presentation.label}
          <span className="sr-only">: {presentation.detail}</span>
        </p>
        {job.status === "FAILED" ||
        job.status === "TRANSLATION_RETRY_WAIT" ? (
          <p className="max-w-sm text-left text-xs leading-5 text-[var(--muted)] lg:text-right">
            {presentation.detail}
            {job.status === "TRANSLATION_RETRY_WAIT" &&
            job.translationNextRetryAt ? (
              <>
                {" "}
                Percobaan berikutnya{" "}
                {dateFormatter.format(new Date(job.translationNextRetryAt))}.
              </>
            ) : null}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2 lg:justify-end">
          {canStartTranslation ? (
            <button
              type="button"
              disabled={isStarting || isDeleting}
              onClick={() => onStartTranslation(job.id)}
              className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting
                ? "Mengantrekan..."
                : job.canRetryTranslation
                  ? "Coba terjemahkan lagi"
                  : "Mulai terjemahan"}
            </button>
          ) : null}
          {job.canRetryPreparation ? (
            <button
              type="button"
              disabled={isStarting || isDeleting}
              onClick={() => onRetryPreparation(job.id)}
              className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting ? "Mengantrekan..." : "Coba siapkan lagi"}
            </button>
          ) : null}
          {job.status === "COMPLETED" && job.resultAvailable ? (
            <a
              href={`/api/jobs/${job.id}/result`}
              className="rounded-[10px] border border-[var(--ink)] bg-[var(--accent)] px-3 py-2 text-xs font-bold text-white transition hover:bg-[var(--accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] active:translate-y-px"
            >
              Unduh PDF
            </a>
          ) : null}
          {canDeleteJob(job.status) ? (
            <button
              type="button"
              disabled={isDeleting || isStarting}
              onClick={() => onDelete(job)}
              className="rounded-[10px] px-3 py-2 text-xs font-bold text-[var(--danger)] transition hover:bg-[var(--accent-wash)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isDeleting ? "Menghapus..." : "Hapus"}
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
