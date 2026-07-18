export type TranslationJobStatus =
  | "QUEUED"
  | "PROCESSING"
  | "READY_FOR_TRANSLATION"
  | "FAILED";


export interface TranslationJob {
  id: string;
  originalFilename: string;
  sizeBytes: number;
  pageCount: number;
  status: TranslationJobStatus;
  createdAt: string;
  startedAt?: string | null;
  preparedAt?: string | null;
  failureCode?: string | null;
}
