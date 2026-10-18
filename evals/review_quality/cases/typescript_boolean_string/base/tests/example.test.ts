import { test } from "node:test";
import { strict as assert } from "node:assert";
import * as subject from "../example";
test("true", () => { assert.equal(subject.enabled("true"), true); });
