import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { App } from "../src/app/App";

describe("App shell", () => {
  it("renders the application name and purpose", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "TenderScore" })).toBeDefined();
    expect(screen.getByText("AI scores, humans moderate, AI documents.")).toBeDefined();
  });

  it("has no axe-core accessibility violations (WCAG 2.2 AA)", async () => {
    const { container } = render(<App />);
    const results = await axe.run(container, {
      // jsdom performs no real layout, so colour-contrast cannot be computed
      // here; it is checked against the rendered UI in browser-based runs.
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
