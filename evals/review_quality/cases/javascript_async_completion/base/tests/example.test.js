const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("empty input", async () => { await subject.saveAll([], async () => {}); });
