import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("active", async () => { assert.equal(await subject.isActive("a", async () => ({ active: true })), true); });
