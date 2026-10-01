import assert from "node:assert/strict";
import { test } from "node:test";

import { highlightLines, languageOf, type Token } from "../src/lib/highlight.ts";

const types = (tokens: Token[]) =>
  tokens.filter((t) => t.v.trim()).map((t) => `${t.t}:${t.v.trim()}`);

test("language detection", () => {
  assert.equal(languageOf("a/b.py"), "python");
  assert.equal(languageOf("x.TSX"), "typescript");
  assert.equal(languageOf("x.mjs"), "javascript");
  assert.equal(languageOf("README.md"), "text");
});

test("python tokens", () => {
  const [line] = highlightLines(
    ['def find(name): return db.query(f"x {name}", 42)  # note'],
    "python",
  );
  assert.deepEqual(types(line ?? []), [
    "kw:def",
    "fn:find",
    "txt:(name):",
    "kw:return",
    "txt:db.",
    "fn:query",
    "txt:(",
    'str:f"x {name}"',
    "txt:,",
    "num:42",
    "txt:)",
    "com:# note",
  ]);
});

test("multi-line strings and block comments carry state", () => {
  const py = highlightLines(['x = """start', "middle", 'end""" + y'], "python");
  assert.equal(py[1]?.[0]?.t, "str");
  assert.equal(py[2]?.[0]?.v, 'end"""');
  assert.equal(py[2]?.at(-1)?.v, " + y"); // adjacent plain text is merged
  const ts = highlightLines(["/* a", "b */ const z = `t", "${q}`;"], "typescript");
  assert.equal(ts[0]?.[0]?.t, "com");
  assert.equal(ts[1]?.[0]?.v, "b */");
  assert.ok(types(ts[1] ?? []).includes("kw:const"));
  assert.equal(ts[2]?.[0]?.t, "str");
});

test("decorators, escapes, text mode", () => {
  const [deco, esc] = highlightLines(['@app.get("/x")', 's = "a\\"b" + c'], "python");
  assert.equal(deco?.[0]?.t, "dec");
  assert.equal(esc?.find((t) => t.t === "str")?.v, '"a\\"b"');
  assert.deepEqual(highlightLines(["plain"], "text"), [[{ t: "txt", v: "plain" }]]);
});
