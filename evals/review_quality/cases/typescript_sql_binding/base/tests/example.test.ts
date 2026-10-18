import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("returns driver result", () => { const db = { query: () => [1] }; assert.deepEqual(subject.findUser(db, "alice"), [1]); });
