import assert from "node:assert/strict";
import test from "node:test";

import {
  parseApiErrorMessage,
  parseJobListResponse,
  parseJobResponse,
} from "./job-contract.ts";


const validJob = {
  id: "0710eb60-e1e6-4f6b-8ddf-dd13fbfa57a3",
  originalFilename: "chapter-01.pdf",
  sizeBytes: 1_024,
  pageCount: 12,
  translatedPageCount: 0,
  translationRetryAttempt: 0,
  translationNextRetryAt: null,
  translationWaitReason: null,
  canResumeTranslation: false,
  canRetryTranslation: false,
  canRetryPreparation: false,
  status: "QUEUED",
  createdAt: "2026-07-14T01:30:00Z",
};

const validPagination = {
  page: 1,
  pageSize: 10,
  totalItems: 1,
  totalPages: 1,
};


test("parseJobListResponse accepts a valid backend response", () => {
  const response = { data: [validJob], pagination: validPagination };

  assert.deepEqual(parseJobListResponse(response), response);
});


test("parseJobResponse validates a created job", () => {
  assert.deepEqual(parseJobResponse(validJob), validJob);
  assert.equal(parseJobResponse({ ...validJob, status: "UNKNOWN" }), null);
});


test("parseJobListResponse accepts every preparation status", () => {
  for (const status of [
    "QUEUED",
    "PROCESSING",
    "READY_FOR_TRANSLATION",
    "TRANSLATION_QUEUED",
    "TRANSLATING",
    "TRANSLATION_RETRY_WAIT",
    "TRANSLATION_STOPPING",
    "TRANSLATION_STOPPED",
    "COMPLETED",
    "FAILED",
  ]) {
    const job =
      status === "TRANSLATION_RETRY_WAIT"
        ? {
            ...validJob,
            status,
            translationRetryAttempt: 1,
            translationNextRetryAt: "2026-07-23T12:30:00+00:00",
            translationWaitReason: "service_unavailable",
            resultAvailable: false,
          }
        : {
            ...validJob,
            status,
            resultAvailable: status === "COMPLETED",
            canResumeTranslation: status === "TRANSLATION_STOPPED",
          };
    const response = { data: [job], pagination: validPagination };
    assert.deepEqual(parseJobListResponse(response), response);
  }
});


test("parseJobResponse accepts watchdog retry wait with zero attempts", () => {
  const job = {
    ...validJob,
    status: "TRANSLATION_RETRY_WAIT",
    translationRetryAttempt: 0,
    translationNextRetryAt: "2026-07-23T12:30:00Z",
    translationWaitReason: "worker_recovery",
  };

  assert.deepEqual(parseJobResponse(job), job);
});


test("parseJobListResponse rejects malformed job data", () => {
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, pageCount: "12" }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, translatedPageCount: -1 }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, translatedPageCount: 13 }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, canResumeTranslation: undefined }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, canRetryTranslation: "yes" }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [{ ...validJob, canRetryPreparation: undefined }],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [
        {
          ...validJob,
          status: "TRANSLATION_RETRY_WAIT",
          translationRetryAttempt: 1,
          translationNextRetryAt: "2026-07-23T12:30:00",
          translationWaitReason: "service_unavailable",
        },
      ],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [
        {
          ...validJob,
          status: "TRANSLATION_RETRY_WAIT",
          translationRetryAttempt: 1,
          translationNextRetryAt: "2026-07-23T12:30:00Z",
          translationWaitReason: "unknown",
        },
      ],
      pagination: validPagination,
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({ data: "not-an-array", pagination: validPagination }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [validJob],
      pagination: { ...validPagination, totalPages: 2 },
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [validJob],
      pagination: { ...validPagination, pageSize: 0 },
    }),
    null,
  );
  assert.equal(
    parseJobListResponse({
      data: [validJob],
      pagination: { ...validPagination, page: "1" },
    }),
    null,
  );
});


test("parseApiErrorMessage only returns a structured error message", () => {
  assert.equal(
    parseApiErrorMessage(
      { error: { code: "INVALID_PDF", message: "Isi file bukan PDF." } },
      "Upload gagal.",
    ),
    "Isi file bukan PDF.",
  );
  assert.equal(
    parseApiErrorMessage({ detail: "internal path leaked" }, "Upload gagal."),
    "Upload gagal.",
  );
});
