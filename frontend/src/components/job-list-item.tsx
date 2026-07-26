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
      ? "border-[var(--danger)] text-[var(--danger)]"
      : "border-[var(--accent-soft)] text-[var(--accent-strong)]";

  return (
    <li className="grid gap-4 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <p className="truncate font-semibold" title={job.originalFilename}>
          {job.originalFilename}
        </p>
        <p className="mt-1 text-sm text-[var(--muted)]">
          {job.pageCount} halaman · {formatBytes(job.sizeBytes)} ·{" "}
          {dateFormatter.format(new Date(job.createdAt))}
        </p>
        {shouldShowTranslationProgress(job.status, job.translatedPageCount) ? (
          <div className="mt-3 max-w-xs">
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
              className="mt-1 h-2 w-full accent-[var(--accent)]"
              max={job.pageCount}
              value={job.translatedPageCount}
            />
          </div>
        ) : null}
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
        {job.status === "FAILED" ||
        job.status === "TRANSLATION_RETRY_WAIT" ? (
          <p className="max-w-xs text-left text-xs leading-5 text-[var(--muted)] sm:text-right">
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
        {canStartTranslation ? (
          <button
            type="button"
            disabled={isStarting || isDeleting}
            onClick={() => onStartTranslation(job.id)}
            className="border border-[var(--accent)] px-3 py-2 text-xs font-semibold text-[var(--accent-strong)] transition hover:bg-[var(--accent)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
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
            className="border border-[var(--accent)] px-3 py-2 text-xs font-semibold text-[var(--accent-strong)] transition hover:bg-[var(--accent)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isStarting ? "Mengantrekan..." : "Coba siapkan lagi"}
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
        {canDeleteJob(job.status) ? (
          <button
            type="button"
            disabled={isDeleting || isStarting}
            onClick={() => onDelete(job)}
            className="border border-[var(--danger)] px-3 py-2 text-xs font-semibold text-[var(--danger)] transition hover:bg-[var(--danger)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isDeleting ? "Menghapus..." : "Hapus"}
          </button>
        ) : null}
      </div>
    </li>
  );
}
