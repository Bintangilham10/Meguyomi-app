export type TranslationJobStatus =
  | "QUEUED"
  | "PROCESSING"
  | "READY_FOR_TRANSLATION"
  | "TRANSLATION_QUEUED"
  | "TRANSLATING"
  | "TRANSLATION_RETRY_WAIT"
  | "TRANSLATION_STOPPING"
  | "TRANSLATION_STOPPED"
  | "COMPLETED"
  | "FAILED";

export type TranslationWaitReason =
  | "rate_limited"
  | "service_unavailable"
  | "worker_recovery"
  | "queue_unavailable";


export interface TranslationJob {
  id: string;
  originalFilename: string;
  sizeBytes: number;
  pageCount: number;
  translatedPageCount: number;
  status: TranslationJobStatus;
  createdAt: string;
  startedAt?: string | null;
  preparedAt?: string | null;
  translationStartedAt?: string | null;
  translationRetryAttempt: number;
  translationNextRetryAt?: string | null;
  translationWaitReason?: TranslationWaitReason | null;
  completedAt?: string | null;
  failureCode?: string | null;
  resultAvailable?: boolean;
  canResumeTranslation: boolean;
  canRetryTranslation: boolean;
  canRetryPreparation: boolean;
}


export interface JobPagination {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}


export interface TranslationJobList {
  data: TranslationJob[];
  pagination: JobPagination;
}
