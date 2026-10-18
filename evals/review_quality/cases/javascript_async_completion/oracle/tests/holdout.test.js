const { test } = require("node:test");
const assert = require("node:assert/strict");
const subject = require("../example.js");
test("wait for all saves", async () => {
  const saved = [];
  await subject.saveAll([1, 2], async (item) => {
    await new Promise((resolve) => setImmediate(resolve));
    saved.push(item);
  });
  assert.deepEqual(saved, [1, 2]);
});
