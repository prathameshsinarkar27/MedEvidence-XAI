import { useCallback, useEffect, useRef, useState } from "react";
import { getMultimodalStatus, startMultimodal } from "../api/client.js";
import { IN_PROGRESS } from "../utils/processing.js";
import StatusBadge from "./StatusBadge.jsx";

const POLL_MS = 1500;

// `onStatus(status)` is called after every fetch; it must be stable (useCallback).
export default function MultimodalPanel({ documentId, textStatus, onStatus }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [imageOcr, setImageOcr] = useState(false);
  const currentId = useRef(documentId);

  const load = useCallback(async () => {
    const id = documentId;
    try {
      const next = await getMultimodalStatus(id);
      if (currentId.current !== id) return;
      setStatus(next);
      setError(null);
      onStatus?.(next);
    } catch (err) {
      if (currentId.current === id) setError(err.message);
    }
  }, [documentId, onStatus]);

  useEffect(() => {
    currentId.current = documentId;
    setStatus(null);
    setError(null);
    load();
  }, [documentId, load]);

  // The automatic pipeline starts this stage after text processing: re-check when the text stage changes.
  useEffect(() => {
    if (textStatus) load();
  }, [textStatus, load]);

  useEffect(() => {
    if (!status || !IN_PROGRESS.includes(status.multimodal_status)) return undefined;
    const timer = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, load]);

  async function run() {
    setStarting(true);
    setError(null);
    try {
      await startMultimodal(documentId, { imageOcr });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || (status && IN_PROGRESS.includes(status.multimodal_status));
  const label = status?.multimodal_status === "not_processed" ? "Find tables & images" : "Run again";
  const skipped = status?.summary
    ? [
        ["tiny images skipped", status.summary.images_skipped_small],
        ["images over the limit", status.summary.images_skipped_over_limit],
        ["tables over the limit", status.summary.tables_skipped_over_limit],
        ["text-less grids skipped", status.summary.tables_skipped_empty],
      ].filter(([, n]) => n > 0)
    : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Tables &amp; embedded images</h2>
        {status && <StatusBadge status={status.multimodal_status} />}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-700">
          {error}
        </p>
      )}

      {status && (
        <div className="mt-3 space-y-3 text-sm text-slate-600">
          {status.page_count != null && (
            <div>
              <p>
                Pages scanned: {status.pages_processed} / {status.page_count}
              </p>
              {busy && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full bg-sky-500 transition-all"
                    style={{ width: `${Math.round((status.pages_processed / Math.max(status.page_count, 1)) * 100)}%` }}
                  />
                </div>
              )}
            </div>
          )}
          {status.table_count != null && (
            <p>
              Found {status.table_count} table{status.table_count === 1 ? "" : "s"} and {status.image_count} image
              {status.image_count === 1 ? "" : "s"}
              {skipped.length > 0 && <span className="text-slate-500"> ({skipped.map(([k, n]) => `${n} ${k}`).join(", ")})</span>}.
            </p>
          )}
          {status.error_message && (
            <div
              role="alert"
              className={`rounded-md border px-3 py-2 ${
                status.multimodal_status === "failed"
                  ? "border-rose-300 bg-rose-50 text-rose-900"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              <p className="font-medium">
                {status.error_code === "ocr_unavailable" ? "Image OCR is not set up" : "Problem during extraction"}
              </p>
              <p className="mt-1 break-words">{status.error_message}</p>
            </div>
          )}
        </div>
      )}

      <label className="mt-4 flex items-start gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={imageOcr} onChange={(e) => setImageOcr(e.target.checked)} className="mt-1" />
        <span>
          Also read text printed inside images (OCR, slower). The picture itself is never interpreted.
        </span>
      </label>
      <button
        type="button"
        onClick={run}
        disabled={busy || !status}
        className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-40"
      >
        {busy ? "Working…" : label}
      </button>
    </section>
  );
}
