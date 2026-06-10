import type { QueueEntry } from "../../api/types";

interface Props {
  procurementTitle: string;
  entries: QueueEntry[];
  onOpen: (entry: QueueEntry) => void;
  onBack: () => void;
}

const TIER_LABELS: Record<QueueEntry["confidence_tier"], string> = {
  escalate: "Escalated — variance beyond one band; human decision required",
  moderate: "Moderate — variance of one band",
  converged: "Converged",
};

export function ModerationQueue({
  procurementTitle,
  entries,
  onOpen,
  onBack,
}: Props): JSX.Element {
  return (
    <section aria-labelledby="queue-heading">
      <nav aria-label="Breadcrumb">
        <button type="button" onClick={onBack}>
          Back to procurements
        </button>
      </nav>
      <h2 id="queue-heading">Moderation queue — {procurementTitle}</h2>
      <p>
        Escalated recommendations are listed first. Every recommendation needs
        a named human decision before the moderation pack can be generated.
      </p>
      {entries.length === 0 ? (
        <p>The queue is empty: no recommendations have been produced yet.</p>
      ) : (
        <table>
          <caption className="visually-hidden">
            Recommendations awaiting moderation, escalated first
          </caption>
          <thead>
            <tr>
              <th scope="col">Question</th>
              <th scope="col">Bidder</th>
              <th scope="col">Recommended score</th>
              <th scope="col">Routing</th>
              <th scope="col">Decision</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.recommendation_id}>
                <td>
                  {entry.criterion_ref} {entry.criterion_title}
                </td>
                <td>Bidder {entry.bidder_id.slice(0, 8)}</td>
                <td>
                  {entry.score === null
                    ? "None — escalated"
                    : String(entry.score)}
                </td>
                <td>{TIER_LABELS[entry.confidence_tier]}</td>
                <td>{entry.decided ? "Decided" : "Awaiting decision"}</td>
                <td>
                  <button type="button" onClick={() => onOpen(entry)}>
                    {entry.decided ? "Review" : "Moderate"}
                    <span className="visually-hidden">
                      {" "}
                      {entry.criterion_ref} for bidder{" "}
                      {entry.bidder_id.slice(0, 8)}
                    </span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
