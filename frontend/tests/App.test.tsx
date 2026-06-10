import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../src/app/App";
import { expectNoAxeViolations } from "./helpers";

describe("App shell", () => {
  it("renders the application name and the sign-in form when signed out", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "TenderScore" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Sign in" })).toBeDefined();
    expect(screen.getByLabelText("Email address")).toBeDefined();
  });

  it("has no axe-core accessibility violations (WCAG 2.2 AA)", async () => {
    const { container } = render(<App />);
    await expectNoAxeViolations(container);
  });
});
