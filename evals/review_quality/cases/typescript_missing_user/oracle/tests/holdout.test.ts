import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("missing user", () => { assert.equal(subject.userName([], 42), "Unknown"); });
