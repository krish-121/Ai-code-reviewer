import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("other JSON values", () => { for (const value of [null, 1, false, "name", {}, { name: 1 }]) assert.equal(subject.readName(value), null); assert.equal(subject.readName({ name: "" }), ""); });
