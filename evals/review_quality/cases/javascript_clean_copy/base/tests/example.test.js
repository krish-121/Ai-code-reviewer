const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("new timeout", () => { assert.equal(subject.withTimeout({ timeout: 3 }, 5).timeout, 5); });
