export type TranslationJobStatus = "QUEUED";


export interface TranslationJob {
  id: string;
  originalFilename: string;
  sizeBytes: number;
  pageCount: number;
  status: TranslationJobStatus;
  createdAt: string;
}
