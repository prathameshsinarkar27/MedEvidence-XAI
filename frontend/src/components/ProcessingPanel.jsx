import { useCallback, useEffect, useRef, useState } from "react";
import { getProcessingStatus, startProcessing } from "../api/client.js";
import { IN_PROGRESS, METHOD_LABELS } from "../utils/processing.js";
import StatusBadge from "./StatusBadge.jsx";

const POLL_MS = 1500;

// `onStatus(status)` is called after every status fetch; `onStatus` must be stable (useCallback).
export default function ProcessingPanel({ documentId, onStatus }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const currentId = useRef(documentId);

  const load = useCallback(async () => {
    const id = documentId;
    try {
      const next = await getProcessingStatus(id);
      if (currentId.current !== id) return; // the user selected another document meanwhile
      setStatus(next);
      setError(null);
      onStatus?.(next);
    } catch (err) {
      if (currentId.current === id) setError(err.message);
    }
  }, [documentId, onStatus]);

  // Fetch once when a document is selected.
  useEffect(() => {
    currentId.current = documentId;
    setStatus(null);
    setError(null);
    load();
  }, [documentId, load]);

  // Poll while a run is queued or in progress. Each fetch produces a new `status`, which re-arms the timer.
  useEffect(() => {
    if (!status || !IN_PROGRESS.includes(status.processing_status)) return undefined;
    const timer = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, load]);

  async function run() {
    setStarting(true);
    setError(null);
    try {
      await startProcessing(documentId);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || (status && IN_PROGRESS.includes(status.processing_status));
  const label = status?.processing_status === "not_processed" ? "Extract text" : "Reprocess";

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Text extraction &amp; OCR</h2>
        {status && <StatusBadge status={status.processing_status} />}
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
                Pages processed: {status.pages_processed} / {status.page_count}
                {status.likely_scanned_pages > 0 && <> &middot; likely scanned: {status.likely_scanned_pages}</>}
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

          {Object.keys(status.pages_by_method).length > 0 && (
            <ul className="flex flex-wrap gap-2 text-xs">
              {Object.entries(status.pages_by_method).map(([method, count]) => (
                <li key={method} className="rounded bg-slate-100 px-2 py-0.5">
                  {METHOD_LABELS[method] ?? method}: {count}
                </li>
              ))}
            </ul>
          )}

          {status.error_message && (
            <div
              role="alert"
              className={`rounded-md border px-3 py-2 text-sm ${
                status.processing_status === "failed"
                  ? "border-rose-300 bg-rose-50 text-rose-900"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              <p className="font-medium">
                {status.error_code === "ocr_unavailable" ? "OCR is not set up" : "Problem during processing"}
              </p>
              <p className="mt-1 break-words">{status.error_message}</p>
            </div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={run}
        disabled={busy || !status}
        className="mt-4 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-40"
      >
        {busy ? "Working…" : label}
      </button>
    </section>
  );
}
