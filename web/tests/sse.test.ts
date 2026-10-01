import assert from "node:assert/strict";
import { test } from "node:test";

import { parseServerSentEvents } from "../src/lib/sse.ts";

test("complete events are parsed and the partial tail is kept", () => {
  const { events, rest } = parseServerSentEvents(
    'event: progress\ndata: {"status":"running"}\n\nevent: done\ndata: {"st',
  );
  assert.deepEqual(events, [{ event: "progress", data: '{"status":"running"}' }]);
  assert.equal(rest, 'event: done\ndata: {"st');
});

test("multi-line data, comments, CRLF and default event names", () => {
  const { events, rest } = parseServerSentEvents(": keep-alive\r\n\r\ndata: a\r\ndata: b\r\n\r\n");
  assert.deepEqual(events, [{ event: "message", data: "a\nb" }]);
  assert.equal(rest, "");
});
