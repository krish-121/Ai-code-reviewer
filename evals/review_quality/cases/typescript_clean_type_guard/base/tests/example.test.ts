import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("name", () => { assert.equal(subject.readName({ name: "Alice" }), "Alice"); });
