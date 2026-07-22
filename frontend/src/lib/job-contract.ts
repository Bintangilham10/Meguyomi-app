import type {
  JobPagination,
  TranslationJob,
  TranslationJobList,
} from "@/types/job";


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
  const translatedPageCountValid =
    Number.isInteger(value.translatedPageCount) &&
    Number(value.translatedPageCount) >= 0 &&
    Number(value.translatedPageCount) <= Number(value.pageCount);

  return (
    typeof value.id === "string" &&
    value.id.length > 0 &&
    typeof value.originalFilename === "string" &&
    value.originalFilename.length > 0 &&
    Number.isInteger(value.sizeBytes) &&
    Number(value.sizeBytes) >= 0 &&
    Number.isInteger(value.pageCount) &&
    Number(value.pageCount) > 0 &&
    translatedPageCountValid &&
    typeof value.status === "string" &&
    validStatuses.has(value.status) &&
    typeof value.createdAt === "string" &&
    !Number.isNaN(Date.parse(value.createdAt)) &&
    optionalDatesValid &&
    failureCodeValid &&
    resultAvailableValid &&
    typeof value.canRetryTranslation === "boolean"
  );
}


function isJobPagination(value: unknown): value is JobPagination {
  if (!isRecord(value)) {
    return false;
  }
  if (
    typeof value.page !== "number" ||
    typeof value.pageSize !== "number" ||
    typeof value.totalItems !== "number" ||
    typeof value.totalPages !== "number"
  ) {
    return false;
  }
  const { page, pageSize, totalItems, totalPages } = value;
  return (
    Number.isInteger(page) &&
    page >= 1 &&
    page <= 10_000 &&
    Number.isInteger(pageSize) &&
    pageSize >= 1 &&
    pageSize <= 50 &&
    Number.isInteger(totalItems) &&
    totalItems >= 0 &&
    Number.isInteger(totalPages) &&
    totalPages === Math.ceil(totalItems / pageSize)
  );
}


export function parseJobListResponse(
  value: unknown,
): TranslationJobList | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value.data) ||
    !isJobPagination(value.pagination)
  ) {
    return null;
  }
  if (
    value.data.length > value.pagination.pageSize ||
    !value.data.every(isTranslationJob)
  ) {
    return null;
  }
  return {
    data: value.data,
    pagination: value.pagination,
  };
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
