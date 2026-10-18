import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("false", () => { assert.equal(subject.enabled("false"), false); });
