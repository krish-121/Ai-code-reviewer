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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function token(): string | null {
  try {
    return window.localStorage.getItem("sentinel.token");
  } catch {
    return null;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;
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
  patchUrl: (id: string) => `/api/fixes/${id}/patch`,
};

export interface ProgressEvent {
  status: ReviewStatus;
  stages: Stage[];
}

/** Subscribe to live pipeline progress (Server-Sent Events). Returns an unsubscribe fn. */
export function subscribeProgress(
  reviewId: string,
  onProgress: (e: ProgressEvent) => void,
  onDone: (status: ReviewStatus) => void,
): () => void {
  const source = new EventSource(`/api/reviews/${reviewId}/events`);
  source.addEventListener("progress", (ev) => {
    onProgress(JSON.parse((ev as MessageEvent<string>).data) as ProgressEvent);
  });
  source.addEventListener("done", (ev) => {
    const data = JSON.parse((ev as MessageEvent<string>).data) as { status: ReviewStatus };
    source.close();
    onDone(data.status);
  });
  source.onerror = () => source.close();
  return () => source.close();
}
