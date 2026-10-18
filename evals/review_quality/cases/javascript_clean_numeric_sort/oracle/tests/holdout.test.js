const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("numeric and immutable", () => { const original = [10, 2, 1]; assert.deepEqual(subject.sortedNumbers(original), [1, 2, 10]); assert.deepEqual(original, [10, 2, 1]); });
