import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("existing user", () => { assert.equal(subject.userName([{ id: 1, name: "Alice" }], 1), "Alice"); });
