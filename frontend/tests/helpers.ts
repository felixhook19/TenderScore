import type axe from "axe-core";
import { expect } from "vitest";

export async function expectNoAxeViolations(container: Element): Promise<void> {
  const axeCore = (await import("axe-core")).default as typeof axe;
  const results = await axeCore.run(container, {
    // jsdom performs no real layout, so colour contrast cannot be computed
    // here; it is checked against the rendered UI in browser-based runs.
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

export function mockFetchRoutes(
  routes: Record<string, { status?: number; body: unknown }>,
): void {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    const route = routes[key];
    if (route === undefined) {
      return new Response(JSON.stringify({ detail: `No mock for ${key}` }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}
