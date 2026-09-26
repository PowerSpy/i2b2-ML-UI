import { useState } from "react";

import { useSession } from "../lib/session.jsx";
import Button from "../ui/Button.jsx";
import { Card } from "../ui/Card.jsx";
import Callout from "../ui/Callout.jsx";
import { Heading, Mono, Note } from "../ui/Text.jsx";

const FIELD =
  "min-h-[44px] w-full rounded-btn border border-border-strong bg-panel-sunk " +
  "px-3 text-[13px] text-text placeholder:text-text-muted";

/**
 * The sign-in screen.
 *
 * Built entirely from the existing ui/ primitives so it inherits the token
 * system and adds no CSS. No "remember me" — the session has a server-side TTL
 * and a browser checkbox cannot extend it. No password reset — the reset path
 * is the CLI on the server, and the form says so rather than offering a link
 * that goes nowhere.
 */
export default function Login() {
  const { login, setupNeeded } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ground px-6">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 text-center">
          <Heading level={1} className="text-[20px] tracking-tight">
            i2b2 ML Workbench
          </Heading>
          <Note className="mt-1.5">Sign in to continue.</Note>
        </div>

        {setupNeeded ? (
          // Nobody can sign in, so the form would be a dead end. Show the fix
          // instead of a field that cannot succeed.
          <Callout tone="warn" title="no accounts exist yet">
            This instance has no users. Create the first one on the server:
            <Mono className="mt-2 block rounded-row border border-border-soft bg-panel-sunk p-3 text-[11px] leading-relaxed break-all text-text-2">
              python -m app.cli create-user --username &lt;you&gt; --role custodian
            </Mono>
          </Callout>
        ) : (
          <Card as="form" onSubmit={submit}>
            <div className="space-y-4">
              <div>
                <label
                  className="mb-1.5 block text-[12px] text-text-3"
                  htmlFor="login-username"
                >
                  username
                </label>
                <input
                  id="login-username"
                  name="username"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className={`${FIELD} font-mono`}
                />
              </div>

              <div>
                <label
                  className="mb-1.5 block text-[12px] text-text-3"
                  htmlFor="login-password"
                >
                  password
                </label>
                <input
                  id="login-password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={FIELD}
                />
              </div>

              {error && (
                <Callout tone="danger" title="could not sign in">
                  {error}
                </Callout>
              )}

              <Button
                type="submit"
                variant="primary"
                className="w-full"
                disabled={busy || !username || !password}
              >
                {busy ? "signing in…" : "Sign in"}
              </Button>
            </div>
          </Card>
        )}

        <Note className="mt-4 text-center">
          Forgotten a password? It can only be reset from the server, with{" "}
          <Mono className="text-text-3">python -m app.cli set-password</Mono>.
        </Note>
      </div>
    </div>
  );
}
