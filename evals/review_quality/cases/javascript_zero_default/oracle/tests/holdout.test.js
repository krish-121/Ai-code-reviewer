const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("zero disables retries", () => { assert.equal(subject.retryLimit({ retries: 0 }), 0); });
