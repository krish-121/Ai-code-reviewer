import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bySeverityThenPriority,
  checkLabel,
  duration,
  groupByFile,
  location,
  pct,
  pluralize,
  relativeTime,
} from "../src/lib/format.ts";
import type { Finding } from "../src/lib/types.ts";

function finding(partial: Partial<Finding>): Finding {
  return {
    id: "F-1",
    category: "bug",
    severity: "low",
    confidence: 0.5,
    title: "t",
    explanation: "",
    file: "a.py",
    line_start: 1,
    line_end: 1,
    evidence: [],
    suggested_fix: null,
    source: "ai",
    origins: [],
    rule_id: null,
    tags: [],
    status: "open",
    fingerprint: "",
    verification: null,
    priority: null,
    in_changed_lines: true,
    merged_ids: [],
    suppressed: false,
    suppressed_reason: null,
    symbol: null,
    review_id: "R-1",
    ...partial,
  };
}

test("durations and percentages", () => {
  assert.equal(pct(0.934), "93%");
  assert.equal(duration(null), "–");
  assert.equal(duration(420), "420 ms");
  assert.equal(duration(3400), "3.4 s");
  assert.equal(duration(42_000), "42 s");
  assert.equal(duration(125_000), "2 min 5 s");
});

test("relative time", () => {
  const now = new Date("2026-01-01T12:00:00Z");
  assert.equal(relativeTime("2026-01-01T11:59:50Z", now), "just now");
  assert.equal(relativeTime("2026-01-01T11:30:00Z", now), "30 min ago");
  assert.equal(relativeTime("2026-01-01T06:00:00Z", now), "6 h ago");
  assert.equal(relativeTime("2025-12-29T12:00:00Z", now), "3 d ago");
  assert.equal(relativeTime(null, now), "");
});

test("locations, labels, plurals", () => {
  assert.equal(location({ file: "a.py", line_start: 3, line_end: 3 }), "a.py:3");
  assert.equal(location({ file: "a.py", line_start: 3, line_end: 5 }), "a.py:3–5");
  assert.equal(checkLabel("probe:sql-injection"), "SQL probe");
  assert.equal(checkLabel("probe:custom-thing"), "custom thing");
  assert.equal(pluralize(1, "finding"), "1 finding");
  assert.equal(pluralize(2, "finding"), "2 findings");
});

test("sorting and grouping", () => {
  const a = finding({ id: "a", severity: "low" });
  const b = finding({ id: "b", severity: "high", priority: { score: 0.2 } as Finding["priority"] });
  const c = finding({
    id: "c",
    severity: "high",
    priority: { score: 0.9 } as Finding["priority"],
    file: "b.py",
  });
  assert.deepEqual(
    [a, b, c].sort(bySeverityThenPriority).map((f) => f.id),
    ["c", "b", "a"],
  );
  const groups = groupByFile([a, b, c]);
  assert.deepEqual([...groups.keys()], ["a.py", "b.py"]);
  assert.equal(groups.get("a.py")?.length, 2);
});
