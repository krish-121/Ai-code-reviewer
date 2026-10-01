import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

// ------------------------------------------------------------------ data fetching

export interface Query<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

const cache = new Map<string, unknown>();

/** Minimal fetch-on-mount hook with a shared cache, keyed reloads and optional polling. */
export function useQuery<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  pollMs?: number,
): Query<T> {
  const [data, setData] = useState<T | undefined>(() =>
    key ? (cache.get(key) as T | undefined) : undefined,
  );
  const [error, setError] = useState<Error | undefined>();
  const [loading, setLoading] = useState<boolean>(key !== null && !cache.has(key));
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    const run = () => {
      fetcherRef
        .current()
        .then((value) => {
          if (cancelled) return;
          cache.set(key, value);
          setData(value);
          setError(undefined);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    setData(cache.get(key) as T | undefined);
    run();
    const timer = pollMs ? window.setInterval(run, pollMs) : undefined;
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [key, tick, pollMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function invalidate(prefix: string): void {
  for (const k of [...cache.keys()]) if (k.startsWith(prefix)) cache.delete(k);
}

// ------------------------------------------------------------------ routing

function subscribe(cb: () => void): () => void {
  window.addEventListener("popstate", cb);
  window.addEventListener("sentinel:navigate", cb);
  return () => {
    window.removeEventListener("popstate", cb);
    window.removeEventListener("sentinel:navigate", cb);
  };
}

export function navigate(to: string): void {
  if (to === window.location.pathname + window.location.search) return;
  window.history.pushState(null, "", to);
  window.dispatchEvent(new Event("sentinel:navigate"));
  window.scrollTo({ top: 0 });
}

export function usePath(): string {
  return useSyncExternalStore(
    subscribe,
    () => window.location.pathname,
    () => "/",
  );
}

export function useSearchParam(name: string): string | null {
  const search = useSyncExternalStore(
    subscribe,
    () => window.location.search,
    () => "",
  );
  return new URLSearchParams(search).get(name);
}

export function setSearchParam(name: string, value: string | null): void {
  const params = new URLSearchParams(window.location.search);
  if (value === null) params.delete(name);
  else params.set(name, value);
  const qs = params.toString();
  window.history.replaceState(null, "", window.location.pathname + (qs ? `?${qs}` : ""));
  window.dispatchEvent(new Event("sentinel:navigate"));
}

// ------------------------------------------------------------------ theme

export type Theme = "light" | "dark" | "system";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (window.localStorage.getItem("sentinel.theme") as Theme | null) ?? "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem("sentinel.theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return [theme, setTheme];
}
