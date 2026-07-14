import assert from "node:assert/strict";
import test from "node:test";

import {
  parseApiErrorMessage,
  parseJobListResponse,
} from "./job-contract.ts";


const validJob = {
  id: "0710eb60-e1e6-4f6b-8ddf-dd13fbfa57a3",
  originalFilename: "chapter-01.pdf",
  sizeBytes: 1_024,
  pageCount: 12,
  status: "QUEUED",
  createdAt: "2026-07-14T01:30:00Z",
};


test("parseJobListResponse accepts a valid backend response", () => {
  assert.deepEqual(parseJobListResponse({ data: [validJob] }), [validJob]);
});


test("parseJobListResponse rejects malformed job data", () => {
  assert.equal(
    parseJobListResponse({ data: [{ ...validJob, pageCount: "12" }] }),
    null,
  );
  assert.equal(parseJobListResponse({ data: "not-an-array" }), null);
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
