const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("binds names separately", () => {
  const calls = [];
  const db = { query: (...args) => { calls.push(args); return []; } };
  subject.findUser(db, "alice' OR 1=1 --");
  assert.deepEqual(calls, [["SELECT id FROM users WHERE name = $1", ["alice' OR 1=1 --"]]]);
});
