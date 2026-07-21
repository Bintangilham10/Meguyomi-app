import assert from "node:assert/strict";
import test from "node:test";

import { canDeleteJob } from "./job-deletion.ts";


test("canDeleteJob permits only jobs without active workers", () => {
  assert.equal(canDeleteJob("READY_FOR_TRANSLATION"), true);
  assert.equal(canDeleteJob("COMPLETED"), true);
  assert.equal(canDeleteJob("FAILED"), true);

  assert.equal(canDeleteJob("QUEUED"), false);
  assert.equal(canDeleteJob("PROCESSING"), false);
  assert.equal(canDeleteJob("TRANSLATION_QUEUED"), false);
  assert.equal(canDeleteJob("TRANSLATING"), false);
});
