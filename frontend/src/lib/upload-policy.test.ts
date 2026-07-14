import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_UPLOAD_BYTES,
  exceedsProxyRequestLimit,
  validatePdfSelection,
} from "./upload-policy.ts";


test("validatePdfSelection accepts a PDF within the upload limit", () => {
  assert.equal(
    validatePdfSelection({
      name: "chapter-01.pdf",
      type: "application/pdf",
      size: MAX_UPLOAD_BYTES,
    }),
    null,
  );
});


test("validatePdfSelection rejects invalid or empty files", () => {
  assert.equal(
    validatePdfSelection({ name: "chapter.png", type: "image/png", size: 20 }),
    "Pilih file PDF.",
  );
  assert.equal(
    validatePdfSelection({ name: "empty.pdf", type: "application/pdf", size: 0 }),
    "PDF tidak boleh kosong.",
  );
});


test("validatePdfSelection rejects a PDF over 50 MB", () => {
  assert.equal(
    validatePdfSelection({
      name: "large.pdf",
      type: "application/pdf",
      size: MAX_UPLOAD_BYTES + 1,
    }),
    "Ukuran PDF maksimal 50 MB.",
  );
});


test("exceedsProxyRequestLimit accounts for multipart overhead", () => {
  assert.equal(exceedsProxyRequestLimit(null), false);
  assert.equal(exceedsProxyRequestLimit("invalid"), false);
  assert.equal(exceedsProxyRequestLimit(String(MAX_UPLOAD_BYTES)), false);
  assert.equal(exceedsProxyRequestLimit(String(MAX_UPLOAD_BYTES + 2_000_000)), true);
});
