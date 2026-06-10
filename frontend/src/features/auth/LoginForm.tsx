import { FormEvent, useState } from "react";

import { ApiError, login, verifyTotp } from "../../api/client";

interface Props {
  onAuthenticated: (sessionToken: string) => void;
}

export function LoginForm({ onAuthenticated }: Props): JSX.Element {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitPassword(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const challenge = await login(email, password);
      setChallengeToken(challenge.challenge_token);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (challengeToken === null) return;
    setBusy(true);
    setError(null);
    try {
      const session = await verifyTotp(challengeToken, code);
      onAuthenticated(session.session_token);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Verification failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (challengeToken !== null) {
    return (
      <form onSubmit={submitCode} aria-describedby={error ? "auth-error" : undefined}>
        <h2>Verification code</h2>
        <p>Enter the six-digit code from your authenticator app.</p>
        <div className="field">
          <label htmlFor="totp-code">Verification code</label>
          <input
            id="totp-code"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            minLength={6}
            maxLength={8}
            required
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </div>
        {error !== null && (
          <p id="auth-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          Verify and sign in
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitPassword} aria-describedby={error ? "auth-error" : undefined}>
      <h2>Sign in</h2>
      <div className="field">
        <label htmlFor="login-email">Email address</label>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error !== null && (
        <p id="auth-error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={busy}>
        Continue
      </button>
    </form>
  );
}
