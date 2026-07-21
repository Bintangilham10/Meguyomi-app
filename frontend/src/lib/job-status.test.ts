import assert from "node:assert/strict";
import test from "node:test";

import {
  getJobStatusPresentation,
  shouldRefreshJobStatus,
  shouldShowTranslationProgress,
} from "./job-status.ts";


test("getJobStatusPresentation describes every translation state", () => {
  assert.equal(getJobStatusPresentation("QUEUED").label, "Menunggu");
  assert.equal(getJobStatusPresentation("PROCESSING").label, "Menyiapkan halaman");
  assert.equal(
    getJobStatusPresentation("READY_FOR_TRANSLATION").label,
    "Siap untuk AI",
  );
  assert.equal(
    getJobStatusPresentation("TRANSLATION_QUEUED").label,
    "Menunggu AI",
  );
  assert.equal(getJobStatusPresentation("TRANSLATING").label, "Menerjemahkan");
  assert.equal(getJobStatusPresentation("COMPLETED").label, "Selesai");
  assert.equal(getJobStatusPresentation("FAILED").label, "Gagal diproses");
});


test("getJobStatusPresentation explains queue failures safely", () => {
  const presentation = getJobStatusPresentation("FAILED", "QUEUE_UNAVAILABLE");

  assert.equal(presentation.label, "Antrean tidak tersedia");
  assert.match(presentation.detail, /coba lagi/i);
});


test("getJobStatusPresentation explains recoverable AI failures", () => {
  const missingConfiguration = getJobStatusPresentation(
    "FAILED",
    "AI_NOT_CONFIGURED",
  );
  const providerFailure = getJobStatusPresentation(
    "FAILED",
    "AI_TRANSLATION_FAILED",
  );

  assert.equal(missingConfiguration.label, "AI belum dikonfigurasi");
  assert.match(missingConfiguration.detail, /GEMINI_API_KEY/);
  assert.equal(providerFailure.label, "Terjemahan AI gagal");
  assert.match(providerFailure.detail, /coba terjemahkan lagi/i);
});


test("getJobStatusPresentation explains exhausted Gemini rate limits", () => {
  const presentation = getJobStatusPresentation("FAILED", "AI_RATE_LIMITED");

  assert.equal(presentation.label, "Batas Gemini tercapai");
  assert.match(presentation.detail, /reset kuota/i);
  assert.match(presentation.detail, /billing/i);
});


test("shouldShowTranslationProgress keeps checkpoint progress visible", () => {
  assert.equal(shouldShowTranslationProgress("TRANSLATION_QUEUED", 7), true);
  assert.equal(shouldShowTranslationProgress("TRANSLATING", 7), true);
  assert.equal(shouldShowTranslationProgress("FAILED", 7), true);
  assert.equal(shouldShowTranslationProgress("FAILED", 0), false);
  assert.equal(shouldShowTranslationProgress("COMPLETED", 10), false);
});


test("shouldRefreshJobStatus only polls active jobs", () => {
  assert.equal(shouldRefreshJobStatus("QUEUED"), true);
  assert.equal(shouldRefreshJobStatus("PROCESSING"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATION_QUEUED"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATING"), true);
  assert.equal(shouldRefreshJobStatus("READY_FOR_TRANSLATION"), false);
  assert.equal(shouldRefreshJobStatus("COMPLETED"), false);
  assert.equal(shouldRefreshJobStatus("FAILED"), false);
});
