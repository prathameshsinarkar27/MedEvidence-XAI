import { useState } from "react";
import { pagePreviewUrl } from "../api/client.js";

// The rendered source page with boxes drawn over it. `boxes` = [{ id, region: {x,y,width,height} (0-1 fractions of
// the displayed page), label, active }]. The image keeps its natural aspect ratio, so percentages line up exactly.
export default function SourcePreview({ documentId, pageNumber, boxes = [], onSelectBox }) {
  // Track which source finished loading (or failed) instead of resetting state in an effect: a cached image can fire
  // onLoad before an effect runs, which would leave the preview stuck on "Loading".
  const src = pagePreviewUrl(documentId, pageNumber);
  const [result, setResult] = useState({ src: null, ok: false });
  const state = result.src !== src ? "loading" : result.ok ? "ready" : "error";

  return (
    <figure className="m-0">
      <div className="relative inline-block max-w-full overflow-hidden rounded-md border border-slate-300 bg-slate-50 align-top">
        <img
          src={src}
          alt={`Source page ${pageNumber}`}
          onLoad={() => setResult({ src, ok: true })}
          onError={() => setResult({ src, ok: false })}
          className="block h-auto max-h-[34rem] w-auto max-w-full"
        />
        {state === "ready" &&
          boxes.map((box) => (
            <button
              type="button"
              key={box.id}
              onClick={() => onSelectBox?.(box.id)}
              aria-label={box.label}
              title={box.label}
              className={`absolute border-2 ${
                box.active ? "border-rose-500 bg-rose-500/15" : "border-sky-500/70 bg-sky-500/5 hover:bg-sky-500/15"
              }`}
              style={{
                left: `${box.region.x * 100}%`,
                top: `${box.region.y * 100}%`,
                width: `${box.region.width * 100}%`,
                height: `${box.region.height * 100}%`,
              }}
            />
          ))}
        {state === "loading" && <p className="absolute inset-0 grid place-items-center text-sm text-slate-500">Loading page…</p>}
      </div>
      {state === "error" && (
        <p role="alert" className="mt-1 text-sm text-rose-700">
          The source page could not be rendered.
        </p>
      )}
      <figcaption className="mt-1 text-xs text-slate-500">
        Source page {pageNumber}. The highlighted box shows where the item was found.
      </figcaption>
    </figure>
  );
}
