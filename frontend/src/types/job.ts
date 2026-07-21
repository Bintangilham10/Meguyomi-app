export type TranslationJobStatus =
  | "QUEUED"
  | "PROCESSING"
  | "READY_FOR_TRANSLATION"
  | "TRANSLATION_QUEUED"
  | "TRANSLATING"
  | "COMPLETED"
  | "FAILED";


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
  completedAt?: string | null;
  failureCode?: string | null;
  resultAvailable?: boolean;
  canRetryTranslation: boolean;
}
