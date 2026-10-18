const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("missing value", () => { assert.equal(subject.retryLimit({}), 3); });
