import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("waits for inactive state", async () => { assert.equal(await subject.isActive("a", async () => ({ active: false })), false); });
