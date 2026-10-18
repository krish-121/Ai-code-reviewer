import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { createElement } from "react";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";

import { api, subscribeProgress } from "../src/lib/api";
import { invalidate } from "../src/lib/hooks";
import { testsReaching } from "../src/lib/testReachability";
import type { CodeGraphJson, Finding, FixAttempt } from "../src/lib/types";
import { FixPanel } from "../src/findings/FixPanel";
import { StatusActions } from "../src/findings/FindingSections";
import { TestsTab } from "../src/review/TestsTab";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
});
const original = { ...api };
const originalFetch = globalThis.fetch;
afterEach(() => {
  cleanup();
  Object.assign(api, original);
  globalThis.fetch = originalFetch;
  invalidate("");
});

for (const failure of ["disconnect", "eof", "http"]) {
  test(`S24: ${failure} recovers through polling and cancellation stops updates`, async () => {
    let calls = 0;
    globalThis.fetch = async (url) => {
      calls++;
      if (String(url).endsWith("/events")) {
        if (failure === "disconnect") throw new Error("connection lost");
        return new Response("", { status: failure === "http" ? 503 : 200 });
      }
      return Response.json({ status: "completed", stages: [] });
    };
    let done = false;
    const stop = subscribeProgress(
      "R1",
      () => {},
      () => {
        done = true;
      },
      5,
    );
    await waitFor(() => assert.equal(done, true));
    stop();
    const previous = calls;
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(calls, previous);
  });
}

function fix(id: string, status: FixAttempt["status"]): FixAttempt {
  return {
    id,
    finding_id: "F",
    status,
    summary: "A generated patch",
    patch: null,
    checks: [],
    isolation: "docker",
    provider: null,
    model: null,
    attempts: 1,
    error: null,
    created_at: null,
    finished_at: null,
    can_apply: false,
  };
}

test("S24: reusing FixPanel for a second attempt restarts polling", async () => {
  let secondCalls = 0;
  api.fix = async (id) => fix(id, id === "one" || ++secondCalls > 1 ? "validated" : "queued");
  const view = render(createElement(FixPanel, { fixId: "one", canApply: false, onApplied() {} }));
  await waitFor(() => assert.match(view.container.textContent ?? "", /A generated patch/));
  view.rerender(createElement(FixPanel, { fixId: "two", canApply: false, onApplied() {} }));
  await waitFor(() => assert.ok(secondCalls >= 2), { timeout: 3500 });
  assert.match(view.container.textContent ?? "", /A generated patch/);
});

test("incomplete validation never offers Apply even if an older API advertises it", async () => {
  api.fix = async (id) => ({ ...fix(id, "unverified"), patch: "proposed diff", can_apply: true });
  const view = render(
    createElement(FixPanel, { fixId: "incomplete", canApply: true, onApplied() {} }),
  );
  await waitFor(() => assert.match(view.container.textContent ?? "", /Complete validation/));
  assert.equal(view.queryByRole("button", { name: "Apply to working tree" }), null);
  assert.ok(view.getByRole("button", { name: "Download patch" }));
});

test("S25: graph errors are visible and retry fetches the graph", async () => {
  let failed = true;
  api.graph = async () => {
    if (failed) throw new Error("graph unavailable");
    return { nodes: [], edges: [] };
  };
  const view = render(createElement(TestsTab, { reviewId: "retry", findings: [] }));
  await waitFor(() => assert.match(view.getByRole("alert").textContent ?? "", /graph unavailable/));
  failed = false;
  fireEvent.click(view.getByRole("button", { name: "Retry" }));
  await waitFor(() => assert.match(view.container.textContent ?? "", /No changed functions/));
});

test("S25: failed status action is shown instead of rejecting an unhandled promise", async () => {
  api.setStatus = async () => {
    throw new Error("write rejected");
  };
  const view = render(
    createElement(StatusActions, {
      finding: { id: "F", status: "open" } as Finding,
      onChanged() {
        assert.fail("failed action reported success");
      },
    }),
  );
  fireEvent.click(view.getByRole("button", { name: "Accept" }));
  await waitFor(() => assert.match(view.getByRole("alert").textContent ?? "", /write rejected/));
});

test("S25: test reachability follows bounded call chains and terminates cycles", () => {
  const graph: CodeGraphJson = {
    nodes: ["test", "helper", "changed"].map((id) => ({
      id,
      name: id,
      kind: id === "test" ? "test" : "function",
      file: "a.py",
      line_start: 1,
      line_end: 2,
      meta: {},
    })),
    edges: [
      ["test", "helper"],
      ["helper", "changed"],
      ["changed", "helper"],
    ].map(([source, target]) => ({ source: source!, target: target!, kind: "calls", line: 1 })),
  };
  assert.deepEqual(
    testsReaching(graph, "changed").map((node) => node.id),
    ["test"],
  );
  assert.equal(testsReaching(graph, "changed", 1).length, 0);
});
