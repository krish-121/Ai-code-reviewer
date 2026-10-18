const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("ascending numbers", () => { assert.deepEqual(subject.sortedNumbers([3, 1, 2]), [1, 2, 3]); });
