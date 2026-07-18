import assert from "node:assert/strict";
import test from "node:test";

import {
  getJobStatusPresentation,
  shouldRefreshJobStatus,
} from "./job-status.ts";


test("getJobStatusPresentation describes every preparation state", () => {
  assert.equal(getJobStatusPresentation("QUEUED").label, "Menunggu");
  assert.equal(getJobStatusPresentation("PROCESSING").label, "Menyiapkan halaman");
  assert.equal(
    getJobStatusPresentation("READY_FOR_TRANSLATION").label,
    "Siap untuk AI",
  );
  assert.equal(getJobStatusPresentation("FAILED").label, "Gagal diproses");
});


test("getJobStatusPresentation explains queue failures safely", () => {
  const presentation = getJobStatusPresentation("FAILED", "QUEUE_UNAVAILABLE");

  assert.equal(presentation.label, "Antrean tidak tersedia");
  assert.match(presentation.detail, /coba lagi/i);
});


test("shouldRefreshJobStatus only polls active jobs", () => {
  assert.equal(shouldRefreshJobStatus("QUEUED"), true);
  assert.equal(shouldRefreshJobStatus("PROCESSING"), true);
  assert.equal(shouldRefreshJobStatus("READY_FOR_TRANSLATION"), false);
  assert.equal(shouldRefreshJobStatus("FAILED"), false);
});
