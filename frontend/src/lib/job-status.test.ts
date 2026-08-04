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
  assert.equal(
    getJobStatusPresentation(
      "TRANSLATION_RETRY_WAIT",
      null,
      "service_unavailable",
    ).label,
    "Menunggu layanan AI",
  );
  assert.equal(
    getJobStatusPresentation("TRANSLATION_STOPPING").label,
    "Menghentikan",
  );
  assert.equal(
    getJobStatusPresentation("TRANSLATION_STOPPED").label,
    "Dihentikan",
  );
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


test("getJobStatusPresentation explains unsafe translation layout", () => {
  const presentation = getJobStatusPresentation(
    "FAILED",
    "RESULT_QUALITY_FAILED",
  );

  assert.equal(presentation.label, "Tata letak perlu dipindai ulang");
  assert.match(presentation.detail, /memindai ulang/i);
});


test("getJobStatusPresentation distinguishes final layout failure reasons", () => {
  const cases = [
    ["RESULT_PLACEMENT_OVERLAP", /bertumpuk/i],
    ["RESULT_SOURCE_MASK_FAILED", /dihapus dengan aman/i],
    ["RESULT_TEXT_FIT_FAILED", /tanpa menutup gambar/i],
  ] as const;

  for (const [failureCode, detailPattern] of cases) {
    const presentation = getJobStatusPresentation("FAILED", failureCode);

    assert.match(presentation.detail, detailPattern);
    assert.equal(presentation.tone, "danger");
  }
});


test("getJobStatusPresentation explains every automatic wait reason", () => {
  assert.match(
    getJobStatusPresentation(
      "TRANSLATION_RETRY_WAIT",
      null,
      "rate_limited",
    ).detail,
    /kuota Gemini/i,
  );
  assert.match(
    getJobStatusPresentation(
      "TRANSLATION_RETRY_WAIT",
      null,
      "worker_recovery",
    ).detail,
    /worker terhenti/i,
  );
  assert.match(
    getJobStatusPresentation(
      "TRANSLATION_RETRY_WAIT",
      null,
      "queue_unavailable",
    ).detail,
    /antrean/i,
  );
});


test("getJobStatusPresentation explains unavailable AI after retries", () => {
  const presentation = getJobStatusPresentation(
    "FAILED",
    "AI_SERVICE_UNAVAILABLE",
  );

  assert.equal(presentation.label, "Layanan AI belum tersedia");
  assert.match(presentation.detail, /coba lagi/i);
});


test("shouldShowTranslationProgress keeps checkpoint progress visible", () => {
  assert.equal(shouldShowTranslationProgress("TRANSLATION_QUEUED", 7), true);
  assert.equal(shouldShowTranslationProgress("TRANSLATING", 7), true);
  assert.equal(
    shouldShowTranslationProgress("TRANSLATION_RETRY_WAIT", 7),
    true,
  );
  assert.equal(shouldShowTranslationProgress("FAILED", 7), true);
  assert.equal(
    shouldShowTranslationProgress("TRANSLATION_STOPPING", 7),
    true,
  );
  assert.equal(
    shouldShowTranslationProgress("TRANSLATION_STOPPED", 7),
    true,
  );
  assert.equal(shouldShowTranslationProgress("FAILED", 0), false);
  assert.equal(shouldShowTranslationProgress("COMPLETED", 10), false);
});


test("shouldRefreshJobStatus only polls active jobs", () => {
  assert.equal(shouldRefreshJobStatus("QUEUED"), true);
  assert.equal(shouldRefreshJobStatus("PROCESSING"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATION_QUEUED"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATING"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATION_RETRY_WAIT"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATION_STOPPING"), true);
  assert.equal(shouldRefreshJobStatus("TRANSLATION_STOPPED"), false);
  assert.equal(shouldRefreshJobStatus("READY_FOR_TRANSLATION"), false);
  assert.equal(shouldRefreshJobStatus("COMPLETED"), false);
  assert.equal(shouldRefreshJobStatus("FAILED"), false);
});
