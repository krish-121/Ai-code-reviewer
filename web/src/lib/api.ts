// Typed client for the Sentinel API. Same-origin; state-changing requests carry the
// X-Sentinel-Client header the server requires (a simple CSRF guard).

import type {
  ChangeSetJson,
  CodeGraphJson,
  Finding,
  FindingDetail,
  FindingStatus,
  FixAttempt,
  Health,
  ReviewDetail,
  ReviewItem,
  Stage,
  ReviewStatus,
} from "./types";
import { parseServerSentEvents, type ServerSentEvent } from "./sse";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "sentinel.token";

/** The API token saved by the sign-in form (token auth mode only). */
function token(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** True when the browser holds an API token from an earlier sign-in. */
export function hasSavedToken(): boolean {
  return Boolean(token());
}

/** Remember (or, with null, forget) the API token for later requests. */
export function saveToken(value: string | null): void {
  try {
    if (value) window.localStorage.setItem(TOKEN_KEY, value);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the user signs in again next time */
  }
}

function authHeaders(): Record<string, string> {
  const t = token();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...authHeaders() };
  if (method !== "GET") headers["X-Sentinel-Client"] = "web";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export interface NewReview {
  path: string;
  mode: "staged" | "worktree" | "range" | "path";
  base?: string;
  head?: string;
  subpath?: string;
}

export const api = {
  health: () => request<Health>("GET", "/api/health"),
  me: () => request<{ id: string; name: string; is_admin: boolean }>("GET", "/api/me"),
  reviews: () => request<ReviewItem[]>("GET", "/api/reviews?limit=100"),
  review: (id: string) => request<ReviewDetail>("GET", `/api/reviews/${id}`),
  findings: (id: string) => request<Finding[]>("GET", `/api/reviews/${id}/findings`),
  files: (id: string) => request<ChangeSetJson>("GET", `/api/reviews/${id}/files`),
  graph: (id: string) => request<CodeGraphJson>("GET", `/api/reviews/${id}/graph`),
  source: (id: string, path: string) =>
    request<{ path: string; content: string }>(
      "GET",
      `/api/reviews/${id}/source?path=${encodeURIComponent(path)}`,
    ),
  createReview: (body: NewReview) => request<{ id: string }>("POST", "/api/reviews", body),
  finding: (id: string) => request<FindingDetail>("GET", `/api/findings/${id}`),
  setStatus: (id: string, status: FindingStatus, note?: string) =>
    request<Finding>("PATCH", `/api/findings/${id}`, { status, note }),
  requestFix: (id: string) => request<{ id: string }>("POST", `/api/findings/${id}/fix`),
  fix: (id: string) => request<FixAttempt>("GET", `/api/fixes/${id}`),
  applyFix: (id: string) => request<{ applied: string[] }>("POST", `/api/fixes/${id}/apply`),
  rejectFix: (id: string) => request<{ status: string }>("POST", `/api/fixes/${id}/reject`),
};

export interface ProgressEvent {
  status: ReviewStatus;
  stages: Stage[];
}

/**
 * Subscribe to live pipeline progress (Server-Sent Events read with fetch, so the
 * Authorization header is sent). Returns an unsubscribe function.
 */
export function subscribeProgress(
  reviewId: string,
  onProgress: (e: ProgressEvent) => void,
  onDone: (status: ReviewStatus) => void,
  pollMs = 2000,
): () => void {
  const controller = new AbortController();
  let finished = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  const done = (status: ReviewStatus) => {
    if (finished || controller.signal.aborted) return;
    finished = true;
    clearTimeout(timer);
    controller.abort();
    onDone(status);
  };
  const poll = async () => {
    try {
      const review = await api.review(reviewId);
      if (controller.signal.aborted) return;
      failures = 0;
      onProgress({ status: review.status, stages: review.stages });
      if (review.status !== "queued" && review.status !== "running") done(review.status);
    } catch {
      failures += 1;
    } finally {
      if (!finished && !controller.signal.aborted)
        timer = setTimeout(poll, Math.min(10000, pollMs * 2 ** Math.min(failures, 3)));
    }
  };
  timer = setTimeout(poll, pollMs);
  const handle = (event: ServerSentEvent) => {
    if (event.event === "progress") onProgress(JSON.parse(event.data) as ProgressEvent);
    if (event.event === "done") done((JSON.parse(event.data) as { status: ReviewStatus }).status);
  };
  void readEvents(`/api/reviews/${reviewId}/events`, controller.signal, handle).catch(() => {
    /* The independent poll also handles silent EOF and interrupted streams. */
  });
  return () => {
    clearTimeout(timer);
    controller.abort();
  };
}

async function readEvents(
  path: string,
  signal: AbortSignal,
  onEvent: (event: ServerSentEvent) => void,
): Promise<void> {
  const res = await fetch(path, {
    headers: { Accept: "text/event-stream", ...authHeaders() },
    signal,
  });
  if (!res.ok || !res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    const parsed = parseServerSentEvents(buffer + value);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }
}
