import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoginForm } from "../src/features/auth/LoginForm";
import { expectNoAxeViolations, mockFetchRoutes } from "./helpers";

describe("LoginForm", () => {
  it("walks both factors and reports the session token", async () => {
    mockFetchRoutes({
      "POST /api/auth/login": {
        body: {
          challenge_token: "challenge-1",
          expires_at: "2026-01-01T00:00:00Z",
          detail: "Enter the verification code from your authenticator app.",
        },
      },
      "POST /api/auth/totp": {
        body: { session_token: "session-1", expires_at: "2026-01-01T12:00:00Z" },
      },
    });
    const onAuthenticated = vi.fn();
    render(<LoginForm onAuthenticated={onAuthenticated} />);

    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "moderator@example.org" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "a-long-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    const codeField = await screen.findByLabelText("Verification code");
    fireEvent.change(codeField, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and sign in" }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("session-1"));
  });

  it("announces authentication errors with role=alert", async () => {
    mockFetchRoutes({
      "POST /api/auth/login": {
        status: 401,
        body: { detail: "Invalid email address or password." },
      },
    });
    render(<LoginForm onAuthenticated={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "moderator@example.org" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Invalid email address or password.");
  });

  it("has no axe-core accessibility violations", async () => {
    const { container } = render(<LoginForm onAuthenticated={() => undefined} />);
    await expectNoAxeViolations(container);
  });
});
