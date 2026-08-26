import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, watchJob } from "./api";
import { Create, SHAPES } from "./components/Create";
import { DeleteControl } from "./components/DeleteControl";
import { Expert } from "./components/Expert";
import { FineTune } from "./components/FineTune";
import { LiveStrip } from "./components/LiveStrip";
import { References } from "./components/References";
import { RenderStage } from "./components/RenderStage";
import { Takes, Waiting } from "./components/Takes";
import { explain } from "./copy";
import { QUALITY_PRESETS } from "./generated/options";
import { DEFAULT_SPEC, applyQualityPreset } from "./spec";
import type { Asset, Job, JobSpec, Plugin, SystemInfo, ValidationReport } from "./types";
import { useEstimates } from "./useEstimates";

export function App() {
  const [spec, setSpec] = useState<JobSpec>(DEFAULT_SPEC);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [refused, setRefused] = useState<string[] | null>(null);
  const [undeleted, setUndeleted] = useState<string | null>(null);
  // Which job is on stage. Null means composing: a job keeps running either way.
  const [staged, setStaged] = useState<number | null>(null);
  const [sheet, setSheet] = useState<{ title: string; body: string; job?: Job } | null>(null);
  // One panel, three tabs. Null means it is closed, which is how it opens.
  const [panel, setPanel] = useState<"picture" | "references" | "expert" | null>(null);
  const streams = useRef(new Map<number, () => void>());

  const refresh = useCallback(async () => {
    const [list, library] = await Promise.all([api.jobs(), api.assets()]);
    setJobs(list);
    setAssets(library);
  }, []);

  useEffect(() => {
    /* Fetch on mount. The state updates land in promise callbacks, not in the
     * effect body, so there is no cascading render to avoid here. */
    /* eslint-disable react-hooks/set-state-in-effect */
    api.system().then(setSystem).catch(() => setSystem(null));
    api.capabilities().then((c) => setPlugins(c.plugins ?? [])).catch(() => setPlugins([]));
    void refresh();
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [refresh]);

  // Follow every unfinished job; each stream closes itself when the job ends.
  useEffect(() => {
    for (const job of jobs) {
      const live = job.state === "queued" || job.state === "running";
      if (live && !streams.current.has(job.id)) {
        const stop = watchJob(job.id, (update) => {
          setJobs((current) =>
            current.map((entry) => (entry.id === update.id ? update : entry)),
          );
          if (update.state !== "queued" && update.state !== "running") {
            streams.current.get(update.id)?.();
            streams.current.delete(update.id);
          }
        });
        streams.current.set(job.id, stop);
      }
    }
  }, [jobs]);

  // Server-side validation, so the browser refuses exactly what h3 refuses.
  useEffect(() => {
    const timer = setTimeout(() => {
      api.validate(spec).then(setReport).catch(() => setReport(null));
    }, 200);
    return () => clearTimeout(timer);
  }, [spec]);

  const variants = useMemo(
    () => [
      ...SHAPES.map((shape) => ({ width: shape.width, height: shape.height })),
      ...QUALITY_PRESETS.map((preset) => {
        const applied = applyQualityPreset(spec, preset.id);
        return {
          steps: applied.steps,
          dit_layers: applied.dit_layers,
          denoise_reuse: applied.denoise_reuse,
          core_reuse: applied.core_reuse,
          token_reduction: applied.token_reduction,
          render_width: applied.render_width,
          render_height: applied.render_height,
        };
      }),
      { steps: spec.steps + 10 },
      { dit_layers: Math.max(35, spec.dit_layers - 5) },
      { denoise_reuse: Math.min(3, spec.denoise_reuse + 1), core_reuse: 1 },
      { render_width: 384, render_height: Math.round((384 * spec.height) / spec.width / 32) * 32 },
    ],
    [spec],
  );
  const estimates = useEstimates(spec, variants);

  const running = jobs.find((job) => job.state === "running") ?? null;
  const onStage = staged !== null ? (jobs.find((job) => job.id === staged) ?? null) : null;
  const blocking = (report?.errors ?? []).filter(
    (message) => message !== "a prompt is required",
  );

  async function make() {
    setRefused(null);
    try {
      const job = await api.submit(spec);
      setJobs((current) => [job, ...current]);
      setStaged(job.id);
    } catch (failure) {
      setRefused(failure instanceof ApiError ? failure.errors : ["The request failed."]);
    }
  }

  async function remove(id: number) {
    setUndeleted(null);
    try {
      await api.remove(id);
      setJobs((current) => current.filter((entry) => entry.id !== id));
      if (staged === id) setStaged(null);
    } catch (failure) {
      setUndeleted(
        failure instanceof ApiError
          ? String(failure.message)
          : "That video could not be deleted.",
      );
    }
  }

  async function cancel(id: number) {
    const job = await api.cancel(id);
    setJobs((current) => current.map((entry) => (entry.id === id ? job : entry)));
  }

  async function showLog(job: Job) {
    const text = await fetch(api.logUrl(job.id)).then((response) =>
      response.ok ? response.text() : "No log was written for this job.",
    );
    setSheet({ title: `Job ${job.id}`, body: text, job });
  }

  const device = system?.device ?? {};
  const problems = [...blocking, ...(refused ?? [])];

  return (
    <div
      data-state={
        onStage?.state === "running" || onStage?.state === "queued"
          ? "rendering"
          : onStage
            ? "watching"
            : "composing"
      }
    >
      <header className="bar">
        <span className="wordmark">
          <b>h3.c</b> <span>studio</span>
        </span>
        <span className="status">
          <span className="dot" />
          {system?.available
            ? `${device.name ?? "GPU"} · ${
              running ? "making a video" : "ready"
            }`
            : (system?.reason ?? "looking for the engine…")}
        </span>
      </header>

      <main>
        <div className="stage">
          {onStage ? (
            <>
              <RenderStage
                job={onStage}
                onLeave={() => setStaged(null)}
                onStop={() => {
                  if (onStage.state === "running") void cancel(onStage.id);
                  setStaged(null);
                }}
              />
              {onStage.state !== "running" ? (
                <div className="go">
                  <button className="make" onClick={() => setStaged(null)}>
                    Make another
                  </button>
                  <span className="total">
                    <a href={api.videoUrl(onStage.id)} download>
                      Download this one
                    </a>
                    {onStage.state === "completed" ? (
                      <DeleteControl
                        label="Delete this one"
                        onDelete={() => remove(onStage.id)}
                      />
                    ) : null}
                  </span>
                </div>
              ) : null}
            </>
          ) : (
            <>
              {running ? (
                <LiveStrip
                  job={running}
                  onWatch={() => setStaged(running.id)}
                  onStop={() => void cancel(running.id)}
                />
              ) : null}
              <Create
                spec={spec}
                assets={assets}
                shapeSeconds={estimates.variants.slice(0, SHAPES.length)}
                qualitySeconds={estimates.variants.slice(
                  SHAPES.length,
                  SHAPES.length + QUALITY_PRESETS.length,
                )}
                totalSeconds={estimates.seconds}
                onChange={setSpec}
                onUploaded={(asset) => setAssets((current) => [asset, ...current])}
                onOpenReferences={() => setPanel("references")}
              />

              {problems.length > 0 ? (
                <p className="wrong" role="status">
                  <b>{explain(problems[0]).title}</b> {explain(problems[0]).fix}
                  <button onClick={() => setSheet({ title: "What h3 reported", body: problems.join("\n") })}>
                    what h3 reported
                  </button>
                </p>
              ) : null}
              {report && report.warnings.length > 0 ? (
                <p className="note">{report.warnings.join(" ")}</p>
              ) : null}

              <div className="go">
                <button
                  className="make"
                  disabled={!spec.prompt.trim() || blocking.length > 0 || !system?.available}
                  onClick={() => void make()}
                >
                  {running ? "Add to the queue" : "Make the video"}
                </button>
                <button
                  className="more"
                  onClick={() => setPanel((open) => (open === null ? "picture" : null))}
                >
                  Everything else {panel === null ? "↓" : "↑"}
                </button>
              </div>

              <Waiting jobs={jobs} onCancel={(id) => void cancel(id)} onLog={showLog} />

              {panel !== null ? (
                <section className="everything">
                  <h2>Everything else</h2>
                  <div className="tabs" role="tablist">
                    {([
                      ["picture", "Picture"],
                      ["references", `Reference material${spec.references.length ? ` (${spec.references.length})` : ""}`],
                      ["expert", "Expert"],
                    ] as const).map(([id, label]) => (
                      <button
                        key={id}
                        role="tab"
                        aria-selected={panel === id}
                        onClick={() => setPanel(id)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {panel === "picture" ? (
                    <FineTune
                      spec={spec}
                      deltas={{
                        base: estimates.seconds,
                        steps: estimates.variants[SHAPES.length + QUALITY_PRESETS.length] ?? null,
                        layers: estimates.variants[SHAPES.length + QUALITY_PRESETS.length + 1] ?? null,
                        reuse: estimates.variants[SHAPES.length + QUALITY_PRESETS.length + 2] ?? null,
                        render: estimates.variants[SHAPES.length + QUALITY_PRESETS.length + 3] ?? null,
                      }}
                      onChange={setSpec}
                    />
                  ) : null}
                  {panel === "references" ? (
                    <References
                      spec={spec}
                      onChange={setSpec}
                      onUploaded={(asset) => setAssets((current) => [asset, ...current])}
                    />
                  ) : null}
                  {panel === "expert" ? (
                    <Expert spec={spec} system={system} plugins={plugins} onChange={setSpec} />
                  ) : null}
                </section>
              ) : null}

            </>
          )}
        </div>
      </main>

      <Takes
        jobs={jobs}
        onOpen={(job) => setStaged(job.id)}
        onDelete={(job) => void remove(job.id)}
      />
      {undeleted ? (
        <p className="note undeleted" role="status">
          {undeleted}
        </p>
      ) : null}

      {sheet ? (
        <div className="modal" onClick={() => setSheet(null)}>
          <section className="sheet" onClick={(event) => event.stopPropagation()}>
            <header>
              {sheet.title}
              <button className="lib" style={{ marginLeft: "auto" }} onClick={() => setSheet(null)}>
                close
              </button>
            </header>
            <div className="pad">
              {sheet.job?.error ? (
                <div className="problem" style={{ marginTop: 0, marginBottom: 12 }}>
                  <b>{explain(sheet.job.error).title}</b>
                  <p>{explain(sheet.job.error).fix}</p>
                </div>
              ) : null}
              <pre className="log">{sheet.body}</pre>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
