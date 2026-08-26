import { useState } from "react";

import { CONSTANTS, QUALITY_PRESETS } from "../generated/options";
import { humanMinutes } from "../copy";
import {
  DEFAULT_SPEC,
  applyQualityPreset,
  matchingPreset,
  resolvedFrames,
  resolvedSeconds,
} from "../spec";
import type { Asset, JobSpec } from "../types";
import { PhotoSlot } from "./PhotoSlot";

interface Props {
  spec: JobSpec;
  assets: Asset[];
  shapeSeconds: (number | null)[];
  qualitySeconds: (number | null)[];
  totalSeconds: number | null;
  onChange: (spec: JobSpec) => void;
  onUploaded: (asset: Asset) => void;
  onOpenReferences: () => void;
}

export const SHAPES = [
  { name: "Widescreen", width: 864, height: 480 },
  { name: "Square", width: 512, height: 512 },
  { name: "Vertical", width: 480, height: 864 },
];

const EXAMPLES = [
  "A red fox walks through fresh snow in a pine forest, tracking shot.",
  "A surfer riding inside a sharp blue ocean wave, realistic spray.",
  "A bright red cube rotates smoothly on a white background.",
];

const PRESET_NAMES: Record<string, string> = {
  draft: "a quick look",
  balanced: "balanced",
  reference: "the best it can",
};

type Open = "length" | "shape" | "quality" | "variation" | "photos" | null;

/** One line of direction, and four words that can be changed.
 *
 *  Everything a person needs to make a video is on this screen, and none of it
 *  is a form: the choices read as a sentence about the shot, and each one
 *  opens where it stands.
 */
export function Create(props: Props) {
  const { spec, assets, shapeSeconds, qualitySeconds, totalSeconds } = props;
  const { onChange, onUploaded, onOpenReferences } = props;
  const [open, setOpen] = useState<Open>(null);
  const requested = spec.seconds ?? resolvedSeconds(spec);
  const preset = matchingPreset(spec);
  const shape = SHAPES.find((s) => s.width === spec.width && s.height === spec.height);
  // Nothing chosen yet is not the same as a choice of your own: on a first
  // visit the quality is simply the one the engine comes with.
  const untouched =
    spec.steps === DEFAULT_SPEC.steps &&
    spec.dit_layers === DEFAULT_SPEC.dit_layers &&
    spec.denoise_reuse === DEFAULT_SPEC.denoise_reuse &&
    spec.core_reuse === DEFAULT_SPEC.core_reuse &&
    spec.token_reduction === DEFAULT_SPEC.token_reduction &&
    spec.render_width === 0;
  const anchored = spec.first_frame !== null || spec.last_frame !== null;
  const anchorsBlocked = spec.references.length > 0;

  const toggle = (which: Open) => setOpen((current) => (current === which ? null : which));
  const word = (which: Open, text: string) => (
    <button className="val" aria-expanded={open === which} onClick={() => toggle(which)}>
      {text}
    </button>
  );

  return (
    <>
      <div className="write">
        <textarea
          className="prompt"
          rows={2}
          value={spec.prompt}
          aria-label="What should the video show?"
          placeholder="Describe the scene: what is in it, what moves, how it is filmed."
          onChange={(event) => onChange({ ...spec, prompt: event.target.value })}
        />
        <div className="under" />
      </div>

      <p className="shot">
        {word("length", `${resolvedSeconds(spec).toFixed(1)} s`)}
        <span className="sep">·</span>
        {word("shape", shape ? shape.name.toLowerCase() : `${spec.width}×${spec.height}`)}
        <span className="sep">·</span>
        {word(
          "quality",
          preset !== null
            ? PRESET_NAMES[preset]
            : untouched
              ? "the settings it comes with"
              : "your own settings",
        )}
        <span className="sep">·</span>
        {word("variation", `variation ${spec.seed}`)}
        <span className="total">
          {totalSeconds === null ? (
            "working out the wait…"
          ) : (
            <>
              about <b>{humanMinutes(totalSeconds)}</b>
            </>
          )}
        </span>
      </p>

      {open === "length" ? (
        <div className="pick wide">
          <input
            type="range"
            min={0.9}
            max={15.1}
            step={0.1}
            value={requested}
            aria-label="Length in seconds"
            onChange={(event) =>
              onChange({ ...spec, seconds: Number(event.target.value), frames: null })
            }
          />
          <p className="note">
            Videos come in fixed lengths. The nearest to {requested.toFixed(1)} s is{" "}
            <b>{resolvedSeconds(spec).toFixed(1)} s</b> — {resolvedFrames(spec)} frames at{" "}
            {CONSTANTS.fps} fps.
          </p>
        </div>
      ) : null}

      {open === "shape" ? (
        <div className="pick">
          {SHAPES.map((entry, index) => (
            <button
              key={entry.name}
              aria-pressed={spec.width === entry.width && spec.height === entry.height}
              onClick={() =>
                onChange({
                  ...spec,
                  width: entry.width,
                  height: entry.height,
                  render_width: 0,
                  render_height: 0,
                })
              }
            >
              <span className="n">{entry.name}</span>
              <span className="cost">
                {entry.width}×{entry.height} ·{" "}
                {shapeSeconds[index] == null ? "…" : humanMinutes(shapeSeconds[index])}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {open === "quality" ? (
        <div className="pick">
          {QUALITY_PRESETS.map((entry, index) => (
            <button
              key={entry.id}
              aria-pressed={preset === entry.id}
              onClick={() => onChange(applyQualityPreset(spec, entry.id))}
            >
              <span className="n">{PRESET_NAMES[entry.id] ?? entry.label}</span>
              <span className="cost">
                {qualitySeconds[index] == null ? "…" : humanMinutes(qualitySeconds[index])}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {open === "variation" ? (
        <div className="pick wide">
          <div className="variation">
            <span className="digits">{spec.seed}</span>
            <button
              className="shuffle"
              onClick={() => onChange({ ...spec, seed: Math.floor(Math.random() * 100000) })}
            >
              Try another
            </button>
          </div>
          <p className="note">Same words and same variation give the same video, every time.</p>
        </div>
      ) : null}

      {open === "photos" ? (
        <div className="pair">
          <PhotoSlot
            title="Start from a photo"
            subtitle="the first frame"
            assets={assets}
            value={spec.first_frame}
            disabled={anchorsBlocked}
            onPick={(asset) => onChange({ ...spec, first_frame: asset?.path ?? null })}
            onUploaded={onUploaded}
          />
          <PhotoSlot
            title="End on a photo"
            subtitle="the last frame"
            assets={assets}
            value={spec.last_frame}
            disabled={anchorsBlocked}
            onPick={(asset) => onChange({ ...spec, last_frame: asset?.path ?? null })}
            onUploaded={onUploaded}
          />
          {anchorsBlocked ? (
            <p className="note">
              Not available while you are using reference material: they are two
              different ways to work.
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="starts">
        <em>or start from</em>
        <button aria-expanded={open === "photos"} onClick={() => toggle("photos")}>
          {anchored ? "the photos you chose" : "a photo"}
        </button>
        <button onClick={onOpenReferences}>
          {spec.references.length > 0
            ? `${spec.references.length} reference${spec.references.length === 1 ? "" : "s"}`
            : "reference material"}
        </button>
      </p>

      {spec.prompt.trim() === "" ? (
        <p className="tries">
          <em>Try:</em>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              className="try"
              onClick={() => onChange({ ...spec, prompt: example })}
            >
              {example.split(" ").slice(0, 4).join(" ").replace(/[,.]$/, "")}
            </button>
          ))}
        </p>
      ) : null}
    </>
  );
}
