import { FormEvent, useState } from "react";

import { ApiError, moderate } from "../../api/client";
import type { RecommendationDetail } from "../../api/types";

interface Props {
  detail: RecommendationDetail;
  onDecided: () => void;
  onBack: () => void;
}

export function RecommendationView({
  detail,
  onDecided,
  onBack,
}: Props): JSX.Element {
  const [action, setAction] = useState<"confirm" | "amend">(
    detail.score === null ? "amend" : "confirm",
  );
  const [finalScore, setFinalScore] = useState<string>(
    detail.score === null ? "" : String(detail.score),
  );
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const summary =
    detail.score === null
      ? `Escalated — variance: ${detail.variance} bands (no recommended score)`
      : `Recommended score: ${detail.score} (${detail.band_label ?? ""}) — ` +
        `${detail.citations.length} citations — variance: ${detail.confidence_tier}`;

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await moderate(
        detail.recommendation_id,
        action,
        action === "amend" ? Number(finalScore) : null,
        action === "amend" ? rationale : null,
      );
      onDecided();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "The decision failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="recommendation-heading">
      <nav aria-label="Breadcrumb">
        <button type="button" onClick={onBack}>
          Back to the queue
        </button>
      </nav>
      <h2 id="recommendation-heading">
        {detail.criterion_ref} {detail.criterion_title}
      </h2>
      <p>{summary}</p>

      <div className="columns">
        <section aria-labelledby="descriptors-heading">
          <h3 id="descriptors-heading">Band descriptors (locked, verbatim)</h3>
          <dl>
            {detail.descriptors.map((descriptor) => (
              <div
                key={descriptor.band}
                className={
                  detail.score === descriptor.band ? "awarded-band" : undefined
                }
              >
                <dt>
                  Band {descriptor.band} ({descriptor.label})
                  {detail.score === descriptor.band
                    ? " — recommended band"
                    : ""}
                </dt>
                <dd>{descriptor.descriptor_text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="evidence-heading">
          <h3 id="evidence-heading">Recommendation and evidence</h3>
          {detail.justification !== "" && (
            <>
              <h4>Justification</h4>
              <p>{detail.justification}</p>
            </>
          )}
          <h4>Citations ({detail.citations.length})</h4>
          {detail.citations.length === 0 ? (
            <p>No citations: the variance routing escalated this question.</p>
          ) : (
            <ul>
              {detail.citations.map((citation, index) => (
                <li key={index}>
                  <blockquote>{citation.span}</blockquote>
                  <p>
                    Supports: {citation.supports} (characters {citation.start}
                    {"–"}
                    {citation.end})
                  </p>
                </li>
              ))}
            </ul>
          )}
          {detail.weaknesses.length > 0 && (
            <>
              <h4>Weaknesses</h4>
              <ul>
                {detail.weaknesses.map((weakness, index) => (
                  <li key={index}>{weakness}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      <form onSubmit={submit} aria-describedby={error ? "decision-error" : undefined}>
        <h3>Your decision</h3>
        <fieldset>
          <legend>Action</legend>
          <div className="field">
            <input
              type="radio"
              id="action-confirm"
              name="action"
              value="confirm"
              checked={action === "confirm"}
              disabled={detail.score === null}
              onChange={() => setAction("confirm")}
            />
            <label htmlFor="action-confirm">
              Confirm the recommended score
              {detail.score === null ? " (unavailable — escalated)" : ""}
            </label>
          </div>
          <div className="field">
            <input
              type="radio"
              id="action-amend"
              name="action"
              value="amend"
              checked={action === "amend"}
              onChange={() => setAction("amend")}
            />
            <label htmlFor="action-amend">Amend the score</label>
          </div>
        </fieldset>

        {action === "amend" && (
          <>
            <div className="field">
              <label htmlFor="final-score">Final score</label>
              <input
                id="final-score"
                name="final_score"
                type="number"
                min={0}
                max={10}
                required
                value={finalScore}
                onChange={(event) => setFinalScore(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="rationale">
                Rationale (required when amending)
              </label>
              <textarea
                id="rationale"
                name="rationale"
                required
                minLength={10}
                rows={4}
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
              />
            </div>
          </>
        )}

        {error !== null && (
          <p id="decision-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          Record decision
        </button>
      </form>
    </section>
  );
}
