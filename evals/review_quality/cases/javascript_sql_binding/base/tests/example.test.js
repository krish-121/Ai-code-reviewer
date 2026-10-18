const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("returns driver result", () => { const db = { query: () => [1] }; assert.deepEqual(subject.findUser(db, "alice"), [1]); });
