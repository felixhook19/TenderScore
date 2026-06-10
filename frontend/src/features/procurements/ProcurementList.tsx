import type { Procurement } from "../../api/types";

interface Props {
  procurements: Procurement[];
  onOpen: (procurement: Procurement) => void;
}

export function ProcurementList({ procurements, onOpen }: Props): JSX.Element {
  if (procurements.length === 0) {
    return (
      <section aria-labelledby="procurements-heading">
        <h2 id="procurements-heading">Procurements</h2>
        <p>No procurements exist yet for your organisation.</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="procurements-heading">
      <h2 id="procurements-heading">Procurements</h2>
      <table>
        <caption className="visually-hidden">
          Procurements available to you, with reference and framework status
        </caption>
        <thead>
          <tr>
            <th scope="col">Title</th>
            <th scope="col">Reference</th>
            <th scope="col">Status</th>
            <th scope="col">Pinned model</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {procurements.map((procurement) => (
            <tr key={procurement.id}>
              <td>{procurement.title}</td>
              <td>{procurement.reference}</td>
              <td>
                {procurement.status === "locked"
                  ? "Framework locked"
                  : "Draft framework"}
              </td>
              <td>{procurement.pinned_model_version ?? "Not pinned"}</td>
              <td>
                <button type="button" onClick={() => onOpen(procurement)}>
                  Open moderation queue
                  <span className="visually-hidden">
                    {" "}
                    for {procurement.title}
                  </span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
