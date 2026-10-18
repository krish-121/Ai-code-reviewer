const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("preserves input and explicit zero", () => { const original = { timeout: 3, label: "x" }; assert.deepEqual(subject.withTimeout(original, 0), { timeout: 0, label: "x" }); assert.equal(original.timeout, 3); });
