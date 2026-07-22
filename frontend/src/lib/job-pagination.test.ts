import assert from "node:assert/strict";
import test from "node:test";

import { parseJobPage } from "./job-pagination.ts";


test("parseJobPage accepts only one safe positive integer", () => {
  assert.equal(parseJobPage("1"), 1);
  assert.equal(parseJobPage("42"), 42);
  assert.equal(parseJobPage(undefined), 1);
  assert.equal(parseJobPage("0"), 1);
  assert.equal(parseJobPage("10001"), 1);
  assert.equal(parseJobPage("1.5"), 1);
  assert.equal(parseJobPage("abc"), 1);
  assert.equal(parseJobPage(["1", "2"]), 1);
});
