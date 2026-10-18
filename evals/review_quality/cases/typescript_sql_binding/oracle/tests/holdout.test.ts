import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("binds names separately", () => {
  const calls: unknown[][] = [];
  const db = { query: (...args: unknown[]) => { calls.push(args); return []; } };
  subject.findUser(db, "alice' OR 1=1 --");
  assert.deepEqual(calls, [["SELECT id FROM users WHERE name = $1", ["alice' OR 1=1 --"]]]);
});
