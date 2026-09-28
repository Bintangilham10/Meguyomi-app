import { canDeleteJob } from "@/lib/job-deletion";
import { sourceLanguageLabel } from "@/lib/source-language";
import {
  getJobStatusPresentation,
  shouldShowTranslationProgress,
} from "@/lib/job-status";
import type { TranslationJob, TranslationJobStatus } from "@/types/job";


interface JobListItemProps {
  job: TranslationJob;
  isDeleting: boolean;
  isPreviewOpen: boolean;
  isStarting: boolean;
  isStopping: boolean;
  onDelete: (job: TranslationJob) => void;
  onTogglePreview: (jobId: string) => void;
  onStartTranslation: (jobId: string) => void;
  onStopTranslation: (jobId: string) => void;
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


function getProgressLabel(status: TranslationJobStatus): string {
  if (
    status === "FAILED" ||
    status === "TRANSLATION_RETRY_WAIT" ||
    status === "TRANSLATION_STOPPED"
  ) {
    return "Checkpoint tersimpan";
  }
  if (status === "TRANSLATION_STOPPING") {
    return "Checkpoint terakhir";
  }
  if (status === "TRANSLATION_QUEUED") {
    return "Akan dilanjutkan";
  }
  return "Progres terjemahan";
}


export function JobListItem({
  job,
  isDeleting,
  isPreviewOpen,
  isStarting,
  isStopping,
  onDelete,
  onTogglePreview,
  onStartTranslation,
  onStopTranslation,
  onRetryPreparation,
}: JobListItemProps) {
  const presentation = getJobStatusPresentation(
    job.status,
    job.failureCode,
    job.translationWaitReason,
  );
  const canStartTranslation =
    job.status === "READY_FOR_TRANSLATION" ||
    job.canRetryTranslation ||
    job.canResumeTranslation;
  const canStopTranslation =
    job.status === "TRANSLATION_QUEUED" ||
    job.status === "TRANSLATING" ||
    job.status === "TRANSLATION_RETRY_WAIT";
  const statusClass =
    presentation.tone === "danger"
      ? "bg-[var(--accent-wash)] text-[var(--danger)]"
      : "bg-[var(--background)] text-[var(--foreground)]";
  const previewId = `result-preview-${job.id}`;
  const previewUrl = `/api/jobs/${job.id}/result?mode=preview`;
  const isPartialResult = job.status === "TRANSLATION_STOPPED";

  return (
    <li className="grid gap-5 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,auto)] lg:items-center">
      <div className="min-w-0">
        <p className="truncate text-lg font-bold" title={job.originalFilename}>
          {job.originalFilename}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--muted)]">
          <span>{sourceLanguageLabel(job.sourceLanguage)} ke Indonesia</span>
          <span>{job.pageCount} halaman</span>
          <span>{formatBytes(job.sizeBytes)}</span>
          <span>{dateFormatter.format(new Date(job.createdAt))}</span>
        </div>
        {shouldShowTranslationProgress(job.status, job.translatedPageCount) ? (
          <div className="mt-4 max-w-md">
            <div className="flex justify-between gap-4 text-xs text-[var(--muted)]">
              <span>
                {getProgressLabel(job.status)}
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
        job.status === "TRANSLATION_RETRY_WAIT" ||
        job.status === "TRANSLATION_STOPPING" ||
        job.status === "TRANSLATION_STOPPED" ? (
          <p className="max-w-sm text-left text-xs leading-5 text-[var(--muted)] lg:text-right">
            {job.status === "TRANSLATION_STOPPED"
              ? job.resultAvailable
                ? "PDF parsial siap dipreview, diunduh, atau dicetak. Terjemahan dapat dilanjutkan dari checkpoint ini."
                : job.translatedPageCount > 0
                  ? "PDF parsial belum dapat disusun, tetapi checkpoint tetap aman dan dapat dilanjutkan."
                  : "Belum ada halaman selesai untuk PDF. Terjemahan dapat dilanjutkan dari checkpoint ini."
              : presentation.detail}
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
              disabled={isStarting || isStopping || isDeleting}
              onClick={() => onStartTranslation(job.id)}
              className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting
                ? "Mengantrekan..."
                : job.canResumeTranslation
                  ? "Lanjutkan terjemahan"
                  : job.canRetryTranslation
                    ? "Coba terjemahkan lagi"
                    : "Mulai terjemahan"}
            </button>
          ) : null}
          {canStopTranslation ? (
            <button
              type="button"
              disabled={isStopping || isStarting || isDeleting}
              onClick={() => onStopTranslation(job.id)}
              className="rounded-[10px] border border-[var(--danger)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold text-[var(--danger)] transition hover:bg-[var(--accent-wash)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStopping ? "Menghentikan..." : "Stop terjemahan"}
            </button>
          ) : null}
          {job.canRetryPreparation ? (
            <button
              type="button"
              disabled={isStarting || isStopping || isDeleting}
              onClick={() => onRetryPreparation(job.id)}
              className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isStarting ? "Mengantrekan..." : "Coba siapkan lagi"}
            </button>
          ) : null}
          {job.resultAvailable ? (
            <>
              <button
                type="button"
                aria-controls={previewId}
                aria-expanded={isPreviewOpen}
                onClick={() => onTogglePreview(job.id)}
                className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              >
                {isPreviewOpen
                  ? "Tutup preview"
                  : isPartialResult
                    ? "Lihat preview parsial"
                    : "Lihat preview"}
              </button>
              <a
                href={`/api/jobs/${job.id}/result`}
                className="rounded-[10px] border border-[var(--ink)] bg-[var(--accent)] px-3 py-2 text-xs font-bold text-white transition hover:bg-[var(--accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] active:translate-y-px"
              >
                {job.status === "TRANSLATION_STOPPED"
                  ? "Unduh PDF parsial"
                  : "Unduh PDF"}
              </a>
              <a
                href={`/api/jobs/${job.id}/result?mode=print`}
                target="_blank"
                rel="noopener noreferrer"
                title="Buka PDF di tab baru untuk dicetak"
                className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              >
                {job.status === "TRANSLATION_STOPPED"
                  ? "Cetak PDF parsial"
                  : "Cetak PDF"}
              </a>
            </>
          ) : null}
          {canDeleteJob(job.status) ? (
            <button
              type="button"
              disabled={isDeleting || isStarting || isStopping}
              onClick={() => onDelete(job)}
              className="rounded-[10px] px-3 py-2 text-xs font-bold text-[var(--danger)] transition hover:bg-[var(--accent-wash)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isDeleting ? "Menghapus..." : "Hapus"}
            </button>
          ) : null}
        </div>
      </div>
      {job.resultAvailable && isPreviewOpen ? (
        <section
          id={previewId}
          aria-label={`Preview hasil ${job.originalFilename}`}
          className="overflow-hidden rounded-[14px] border border-[var(--border-strong)] bg-[var(--surface-strong)] lg:col-span-2"
        >
          <div className="flex flex-col gap-4 border-b border-[var(--border)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div>
              <p className="display-face text-xl">
                {isPartialResult ? "Preview PDF parsial" : "Preview PDF hasil"}
              </p>
              <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                {isPartialResult
                  ? `${job.translatedPageCount} dari ${job.pageCount} halaman telah selesai dan tersimpan.`
                  : `${job.pageCount} halaman hasil terjemahan siap diperiksa.`}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a
                href={previewUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-[10px] border border-[var(--ink)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              >
                Buka di tab baru
              </a>
              <button
                type="button"
                onClick={() => onTogglePreview(job.id)}
                className="rounded-[10px] px-3 py-2 text-xs font-bold text-[var(--muted)] transition hover:bg-[var(--background)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              >
                Tutup
              </button>
            </div>
          </div>
          <iframe
            src={previewUrl}
            title={`Preview PDF ${job.originalFilename}`}
            loading="lazy"
            className="block h-[65svh] min-h-[28rem] w-full bg-white sm:h-[46rem]"
          />
          <p className="border-t border-[var(--border)] px-4 py-3 text-xs leading-5 text-[var(--muted)] sm:px-5">
            Jika PDF tidak tampil di perangkat ini, gunakan tombol Buka di tab
            baru. File tetap bersifat privat dan tidak disimpan di cache browser.
          </p>
        </section>
      ) : null}
    </li>
  );
}
