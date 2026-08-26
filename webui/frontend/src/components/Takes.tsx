import { api } from "../api";
import { clock, stateName } from "../copy";
import type { Job } from "../types";
import { DeleteControl } from "./DeleteControl";

interface Props {
  jobs: Job[];
  onOpen: (job: Job) => void;
  onDelete: (job: Job) => void;
}

/** Everything this machine has made, most recent first. */
export function Takes({ jobs, onOpen, onDelete }: Props) {
  const done = jobs.filter((job) => job.state === "completed");
  return (
    <section className="takes">
      <h2>Takes</h2>
      {done.length === 0 ? (
        <div className="empty">
          Nothing made yet. Describe a scene above and the first take lands here.
        </div>
      ) : (
        <div className="strip">
          {done.map((job) => (
            // A card, not a button: the delete control lives inside it, and a
            // button cannot hold another one.
            <div key={job.id} className="take">
              <button className="open" onClick={() => onOpen(job)}>
                <img className="thumb" src={api.posterUrl(job.id)} alt="" />
                <span className="cap">
                  <b>{job.prompt.split(" ").slice(0, 4).join(" ")}</b>
                  <span>{clock(job.elapsed)}</span>
                </span>
              </button>
              <div className="cap acts">
                <DeleteControl label="delete" onDelete={() => onDelete(job)} />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Jobs that are not the one on stage: waiting, stopped or broken. */
export function Waiting({ jobs, onCancel, onLog }: {
  jobs: Job[];
  onCancel: (id: number) => void;
  onLog: (job: Job) => void;
}) {
  const others = jobs.filter(
    (job) => job.state === "queued" || job.state === "failed" || job.state === "cancelled",
  );
  if (others.length === 0) return null;
  return (
    <div className="queued">
      {others.slice(0, 6).map((job) => (
        <div className="one" key={job.id}>
          <span className="st">{stateName(job.state)}</span>
          <span className="t">{job.prompt || "(no description)"}</span>
          {job.state === "queued" ? (
            <button className="lib" onClick={() => onCancel(job.id)}>
              remove
            </button>
          ) : (
            <button className="lib" onClick={() => onLog(job)}>
              what happened
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
