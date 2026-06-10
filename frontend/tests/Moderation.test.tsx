import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { QueueEntry, RecommendationDetail } from "../src/api/types";
import { ModerationQueue } from "../src/features/moderation/ModerationQueue";
import { RecommendationView } from "../src/features/moderation/RecommendationView";
import { expectNoAxeViolations, mockFetchRoutes } from "./helpers";

const ENTRIES: QueueEntry[] = [
  {
    recommendation_id: "rec-escalated",
    run_id: "run-1",
    criterion_id: "crit-1",
    criterion_ref: "Q4",
    criterion_title: "Environmental Management",
    bidder_id: "bidder-aaaa-1111",
    score: null,
    confidence_tier: "escalate",
    variance: 2,
    decided: false,
  },
  {
    recommendation_id: "rec-converged",
    run_id: "run-2",
    criterion_id: "crit-2",
    criterion_ref: "Q1",
    criterion_title: "Mobilisation",
    bidder_id: "bidder-bbbb-2222",
    score: 3,
    confidence_tier: "converged",
    variance: 0,
    decided: true,
  },
];

const DETAIL: RecommendationDetail = {
  recommendation_id: "rec-converged",
  criterion_ref: "Q1",
  criterion_title: "Mobilisation",
  score: 3,
  band_label: "Good",
  justification: "The answer names leads and gives a credible programme.",
  citations: [
    {
      span: "named lead for every workstream",
      start: 10,
      end: 41,
      supports: "Ownership is explicit.",
    },
  ],
  requirements: { met: ["R1"], partial: [], not_met: [] },
  weaknesses: ["No contingency for equipment failure."],
  variance: 0,
  confidence_tier: "converged",
  descriptors: [
    { band: 1, label: "Poor", descriptor_text: "Addresses little." },
    { band: 3, label: "Good", descriptor_text: "Meets the requirement." },
    { band: 5, label: "Excellent", descriptor_text: "Exceeds it." },
  ],
};

describe("ModerationQueue", () => {
  it("lists escalations with their routing explanation", () => {
    render(
      <ModerationQueue
        procurementTitle="Grounds Maintenance Services"
        entries={ENTRIES}
        onOpen={() => undefined}
        onBack={() => undefined}
      />,
    );
    expect(
      screen.getByText(
        "Escalated — variance beyond one band; human decision required",
      ),
    ).toBeDefined();
    expect(screen.getByText("None — escalated")).toBeDefined();
  });

  it("has no axe-core accessibility violations", async () => {
    const { container } = render(
      <ModerationQueue
        procurementTitle="Grounds Maintenance Services"
        entries={ENTRIES}
        onOpen={() => undefined}
        onBack={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describe("RecommendationView", () => {
  it("shows descriptors side by side with the recommendation evidence", () => {
    render(
      <RecommendationView
        detail={DETAIL}
        onDecided={() => undefined}
        onBack={() => undefined}
      />,
    );
    expect(
      screen.getByText("Band 3 (Good) — recommended band"),
    ).toBeDefined();
    expect(screen.getByText("named lead for every workstream")).toBeDefined();
  });

  it("requires a rationale when amending", async () => {
    render(
      <RecommendationView
        detail={DETAIL}
        onDecided={() => undefined}
        onBack={() => undefined}
      />,
    );
    fireEvent.click(screen.getByLabelText("Amend the score"));
    const rationale = screen.getByLabelText("Rationale (required when amending)");
    expect(rationale.hasAttribute("required")).toBe(true);
  });

  it("submits a confirmation decision", async () => {
    mockFetchRoutes({
      "POST /api/recommendations/rec-converged/moderate": {
        status: 201,
        body: {
          id: "decision-1",
          recommendation_id: "rec-converged",
          action: "confirm",
          final_score: 3,
          rationale: null,
        },
      },
    });
    const onDecided = vi.fn();
    render(
      <RecommendationView
        detail={DETAIL}
        onDecided={onDecided}
        onBack={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
  });

  it("disables confirm for escalated recommendations", () => {
    render(
      <RecommendationView
        detail={{ ...DETAIL, score: null, citations: [], confidence_tier: "escalate" }}
        onDecided={() => undefined}
        onBack={() => undefined}
      />,
    );
    const confirm = screen.getByLabelText(
      "Confirm the recommended score (unavailable — escalated)",
    );
    expect(confirm.hasAttribute("disabled")).toBe(true);
  });

  it("has no axe-core accessibility violations", async () => {
    const { container } = render(
      <RecommendationView
        detail={DETAIL}
        onDecided={() => undefined}
        onBack={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
  });
});
