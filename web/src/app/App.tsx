import { useEffect } from "react";

import { api, ApiError, hasSavedToken } from "../lib/api";
import { navigate, usePath, useQuery, useTheme, type Theme } from "../lib/hooks";
import { ReviewPage } from "../pages/ReviewPage";
import { ReviewsPage } from "../pages/ReviewsPage";
import { SignIn } from "./SignIn";

const UNAUTHORIZED = 401;

function Logo() {
  return (
    <svg className="logo-mark" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.5 20 6v6.2c0 4.6-3.3 8.3-8 9.3-4.7-1-8-4.7-8-9.3V6l8-3.5Z" />
      <path className="logo-check" d="m8.3 12.2 2.5 2.5 4.9-5.2" />
    </svg>
  );
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function App() {
  const path = usePath();
  const [theme, setTheme] = useTheme();
  const health = useQuery("health", api.health);
  const me = useQuery("me", api.me);
  const needsSignIn = me.error instanceof ApiError && me.error.status === UNAUTHORIZED;

  const reviewMatch = /^\/reviews\/([^/]+)(?:\/findings\/([^/]+))?/.exec(path);
  useEffect(() => {
    document.title = reviewMatch ? `Review ${reviewMatch[1]} · Sentinel` : "Sentinel";
  }, [reviewMatch?.[1]]);

  return (
    <div className="shell">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("/");
          }}
        >
          <Logo />
          <span>Sentinel</span>
        </a>
        <nav className="topnav" aria-label="Main">
          <a
            href="/"
            aria-current={reviewMatch ? undefined : "page"}
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            Reviews
          </a>
        </nav>
        <div className="topbar-right">
          {health.data ? (
            <span className="engine" title="AI provider configured on the server">
              {health.data.provider === "none"
                ? "Static analysis only"
                : `Default AI: ${health.data.provider}`}
            </span>
          ) : null}
          {health.data && health.data.queue > 0 ? (
            <span className="queue">{health.data.queue} in queue</span>
          ) : null}
          <div className="theme-switch" role="radiogroup" aria-label="Color theme">
            {THEMES.map((t) => (
              <button
                key={t.value}
                role="radio"
                aria-checked={theme === t.value}
                className={theme === t.value ? "on" : ""}
                onClick={() => setTheme(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main className="main">
        {needsSignIn ? (
          <SignIn invalid={hasSavedToken()} />
        ) : reviewMatch ? (
          <ReviewPage reviewId={reviewMatch[1] ?? ""} findingId={reviewMatch[2] ?? null} />
        ) : (
          <ReviewsPage />
        )}
      </main>
    </div>
  );
}
