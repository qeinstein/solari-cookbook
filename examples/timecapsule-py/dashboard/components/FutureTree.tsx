import type { Future } from "../lib/types";
import { branchEventLabel, failureLabel } from "../lib/presentation";

type Branch = { future: Future; children: Branch[] };

function branches(futures: Future[]) {
  const byId = new Map(futures.map((future) => [future.future_id, { future, children: [] as Branch[] }]));
  const roots: Branch[] = [];
  for (const branch of byId.values()) {
    const parentId = branch.future.search?.parent_future_id;
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) parent.children.push(branch);
    else roots.push(branch);
  }
  return roots;
}

function BranchRow({
  branch,
  selectedId,
  index,
  onSelect,
}: {
  branch: Branch;
  selectedId?: string;
  index: number;
  onSelect: (future: Future) => void;
}) {
  const { future } = branch;
  const shared = future.search?.shared_prefix_events ?? 1;
  return (
    <li className="branch-node">
      <button
        className={`future-row ${future.status.toLowerCase()} ${selectedId === future.future_id ? "selected" : ""}`}
        type="button"
        aria-pressed={selectedId === future.future_id}
        style={{ animationDelay: `${Math.min(index, 10) * 35}ms` }}
        onClick={() => onSelect(future)}
      >
        <span className="branch-joint" aria-hidden="true" />
        <span className="future-id">
          <strong>{future.future_id}</strong>
          <small>{future.search?.mutation === "seed" ? "seed branch" : future.search?.mutation?.replaceAll("_", " ")}</small>
        </span>
        <span className="events" aria-label={`Events in ${future.future_id}`}>
          {future.events.map((event, eventIndex) => (
            <span className="event-group" key={`${event.at}-${event.kind}-${eventIndex}`}>
              {eventIndex > 0 ? <span className="arrow" aria-hidden="true">→</span> : null}
              <span className="event"><span className="event-dot" aria-hidden="true" />{branchEventLabel(event)}</span>
            </span>
          ))}
        </span>
        <span className="branch-meta">
          {future.failure_modes?.map((mode) => <small key={mode}>{failureLabel(mode)}</small>)}
          <b className={`result ${future.status}`}>{future.status}</b>
        </span>
      </button>
      {future.search?.parent_future_id ? <div className="prefix-proof">↳ {shared} event{shared === 1 ? "" : "s"} shared with {future.search.parent_future_id}</div> : null}
      {branch.children.length ? (
        <ul className="branch-children">
          {branch.children.map((child, childIndex) => (
            <BranchRow
              key={child.future.future_id}
              branch={child}
              selectedId={selectedId}
              index={index + childIndex + 1}
              onSelect={onSelect}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function FutureTree({
  futures,
  selectedId,
  onSelect,
}: {
  futures: Future[];
  selectedId?: string;
  onSelect: (future: Future) => void;
}) {
  const roots = branches(futures);
  return (
    <>
      <div className="branch-root"><span className="root-node" aria-hidden="true" />Shared world <b>INV-1842</b><span>invoice + initial state</span></div>
      <ul className="future-tree" aria-label="Coverage-guided future branches">
        {roots.map((branch, index) => (
          <BranchRow
            key={branch.future.future_id}
            branch={branch}
            selectedId={selectedId}
            index={index}
            onSelect={onSelect}
          />
        ))}
      </ul>
    </>
  );
}
