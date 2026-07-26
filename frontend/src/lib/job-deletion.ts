import type { TranslationJobStatus } from "@/types/job";


const DELETABLE_JOB_STATUSES = new Set<TranslationJobStatus>([
  "READY_FOR_TRANSLATION",
  "TRANSLATION_RETRY_WAIT",
  "COMPLETED",
  "FAILED",
]);


export function canDeleteJob(status: TranslationJobStatus): boolean {
  return DELETABLE_JOB_STATUSES.has(status);
}
