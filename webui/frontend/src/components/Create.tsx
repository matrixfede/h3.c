import { CONSTANTS, QUALITY_PRESETS } from "../generated/options";
import { humanMinutes, timecode } from "../copy";
import { applyQualityPreset, matchingPreset, resolvedFrames, resolvedSeconds } from "../spec";
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
}

export const SHAPES = [
  { name: "Widescreen", width: 864, height: 480, w: 44, h: 25 },
  { name: "Square", width: 512, height: 512, w: 32, h: 32 },
  { name: "Vertical", width: 480, height: 864, w: 25, h: 44 },
];

const EXAMPLES = [
  "A red fox walks through fresh snow in a pine forest, tracking shot.",
  "A surfer riding inside a sharp blue ocean wave, realistic spray.",
  "A bright red cube rotates smoothly on a white background.",
];

export function Create(props: Props) {
  const { spec, assets, shapeSeconds, qualitySeconds, totalSeconds } = props;
  const { onChange, onUploaded } = props;
  const requested = spec.seconds ?? resolvedSeconds(spec);
  const preset = matchingPreset(spec);
  const anchorsBlocked = spec.references.length > 0;

  return (
    <>
      <h1 className="ask">What should the video show?</h1>
      <textarea
        className="prompt"
        value={spec.prompt}
        placeholder="Describe the scene: what is in it, what moves, how it is filmed."
        onChange={(event) => onChange({ ...spec, prompt: event.target.value })}
      />
      <div className="tries">
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
      </div>

      <div className="block">
        <div className="label">
          How long <span className="flag">--seconds</span>
        </div>
        <div className="timecode">
          <span className="value">{timecode(requested)}</span>
          <span className="unit">seconds · {CONSTANTS.fps} fps</span>
        </div>
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
          <b>{resolvedSeconds(spec).toFixed(1)} s</b> — {resolvedFrames(spec)} frames.
          {totalSeconds !== null ? (
            <span className="cost">≈ {humanMinutes(totalSeconds)} to make</span>
          ) : null}
        </p>
      </div>

      <div className="block">
        <div className="label">
          Shape <span className="flag">--width --height</span>
        </div>
        <div className="shapes">
          {SHAPES.map((shape, index) => (
            <button
              key={shape.name}
              className="shape"
              aria-pressed={spec.width === shape.width && spec.height === shape.height}
              onClick={() =>
                onChange({
                  ...spec,
                  width: shape.width,
                  height: shape.height,
                  render_width: 0,
                  render_height: 0,
                })
              }
            >
              <i style={{ width: shape.w, height: shape.h }} />
              <span className="n">{shape.name}</span>
              <span className="d">
                {shape.width}×{shape.height}
              </span>
              <span className="cost">
                {shapeSeconds[index] === null || shapeSeconds[index] === undefined
                  ? "…"
                  : `≈ ${humanMinutes(shapeSeconds[index])}`}
              </span>
            </button>
          ))}
        </div>
        <p className="note">
          Bigger pictures take longer. The largest this model was released for is{" "}
          <b>1344 × 768</b>. Other sizes are in <b>Fine-tune</b>.
        </p>
      </div>

      <div className="block">
        <div className="label">
          Quality <span className="flag">--steps --layers --reuse</span>
        </div>
        <div className="cards">
          {QUALITY_PRESETS.map((entry, index) => (
            <button
              key={entry.id}
              className="card"
              aria-pressed={preset === entry.id}
              onClick={() => onChange(applyQualityPreset(spec, entry.id))}
            >
              <span className="name">{PRESET_NAMES[entry.id] ?? entry.label}</span>
              <span className="cost">
                {qualitySeconds[index] === null || qualitySeconds[index] === undefined
                  ? "…"
                  : `≈ ${humanMinutes(qualitySeconds[index])}`}
              </span>
              <span className="what">{PRESET_WHAT[entry.id]}</span>
            </button>
          ))}
        </div>
        {preset === null ? (
          <p className="note">
            Your own settings, from <b>Fine-tune</b>.
          </p>
        ) : null}
      </div>

      <div className="block">
        <div className="label">
          Start and end <span className="flag">--first-frame --last-frame</span>
        </div>
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
        </div>
        <p className="note">
          {anchorsBlocked
            ? "Not available while you are using reference material: they are two different ways to work."
            : "Optional. Add a photo and the video begins — or ends — there."}
        </p>
      </div>

      <div className="block">
        <div className="label">
          Variation <span className="flag">--seed</span>
        </div>
        <div className="variation">
          <span className="digits">{spec.seed}</span>
          <button
            className="shuffle"
            onClick={() =>
              onChange({ ...spec, seed: Math.floor(Math.random() * 100000) })
            }
          >
            Try another
          </button>
          <span className="note" style={{ margin: 0 }}>
            Same settings and same variation give the same video, every time.
          </span>
        </div>
      </div>
    </>
  );
}

const PRESET_NAMES: Record<string, string> = {
  draft: "Quick look",
  balanced: "Balanced",
  reference: "Best quality",
};

const PRESET_WHAT: Record<string, string> = {
  draft: "Rough, for checking the idea.",
  balanced: "Good detail, sensible wait.",
  reference: "Every pass, nothing skipped.",
};
