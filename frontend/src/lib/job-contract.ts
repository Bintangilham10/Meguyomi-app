import type { TranslationJob } from "@/types/job";


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}


function isTranslationJob(value: unknown): value is TranslationJob {
  if (!isRecord(value)) {
    return false;
  }

  const validStatuses = new Set([
    "QUEUED",
    "PROCESSING",
    "READY_FOR_TRANSLATION",
    "TRANSLATION_QUEUED",
    "TRANSLATING",
    "COMPLETED",
    "FAILED",
  ]);
  const optionalDatesValid = [
    value.startedAt,
    value.preparedAt,
    value.translationStartedAt,
    value.completedAt,
  ].every(
    (date) =>
      date === undefined ||
      date === null ||
      (typeof date === "string" && !Number.isNaN(Date.parse(date))),
  );
  const failureCodeValid =
    value.failureCode === undefined ||
    value.failureCode === null ||
    (typeof value.failureCode === "string" && value.failureCode.length <= 64);
  const resultAvailableValid =
    value.resultAvailable === undefined ||
    typeof value.resultAvailable === "boolean";

  return (
    typeof value.id === "string" &&
    value.id.length > 0 &&
    typeof value.originalFilename === "string" &&
    value.originalFilename.length > 0 &&
    Number.isInteger(value.sizeBytes) &&
    Number(value.sizeBytes) >= 0 &&
    Number.isInteger(value.pageCount) &&
    Number(value.pageCount) > 0 &&
    typeof value.status === "string" &&
    validStatuses.has(value.status) &&
    typeof value.createdAt === "string" &&
    !Number.isNaN(Date.parse(value.createdAt)) &&
    optionalDatesValid &&
    failureCodeValid &&
    resultAvailableValid
  );
}


export function parseJobListResponse(value: unknown): TranslationJob[] | null {
  if (!isRecord(value) || !Array.isArray(value.data)) {
    return null;
  }
  return value.data.every(isTranslationJob) ? value.data : null;
}


export function parseJobResponse(value: unknown): TranslationJob | null {
  return isTranslationJob(value) ? value : null;
}


export function parseApiErrorMessage(value: unknown, fallback: string): string {
  if (!isRecord(value) || !isRecord(value.error)) {
    return fallback;
  }
  const message = value.error.message;
  if (typeof message !== "string" || message.length < 1 || message.length > 500) {
    return fallback;
  }
  return message;
}
