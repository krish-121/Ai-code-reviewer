// Shown when the server runs in token mode and no valid API token is saved yet.

import { type FormEvent, useState } from "react";

import { saveToken } from "../lib/api";

export function SignIn({ invalid }: { invalid: boolean }) {
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    saveToken(value.trim());
    window.location.reload();
  };
  return (
    <section className="page signin">
      <h1>Sign in</h1>
      <p className="lede">
        This Sentinel server requires an API token. An administrator creates one with{" "}
        <code>sentinel users create &lt;name&gt;</code>.
      </p>
      {invalid ? <p className="form-error">That token was not accepted.</p> : null}
      <form className="new-review" onSubmit={submit} aria-label="Sign in with an API token">
        <label>
          API token
          <input
            required
            autoFocus
            type="password"
            autoComplete="current-password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <div className="actions">
          <button type="submit" className="btn btn-primary">
            Sign in
          </button>
        </div>
      </form>
    </section>
  );
}
