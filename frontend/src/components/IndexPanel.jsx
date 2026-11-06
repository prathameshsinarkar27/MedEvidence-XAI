import { useCallback, useEffect, useRef, useState } from "react";
import { getIndexStatus, startIndexing } from "../api/client.js";
import { IN_PROGRESS } from "../utils/processing.js";
import StatusBadge from "./StatusBadge.jsx";

const POLL_MS = 1500;

// Evidence index status of one document. Indexing normally runs automatically after clinical extraction.
export default function IndexPanel({ documentId, clinicalStatus }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const currentId = useRef(documentId);

  const load = useCallback(async () => {
    const id = documentId;
    try {
      const next = await getIndexStatus(id);
      if (currentId.current !== id) return;
      setStatus(next);
      setError(null);
    } catch (err) {
      if (currentId.current === id) setError(err.message);
    }
  }, [documentId]);

  useEffect(() => {
    currentId.current = documentId;
    setStatus(null);
    load();
  }, [documentId, load]);

  // Indexing follows clinical extraction: re-check when that changes.
  useEffect(() => {
    if (clinicalStatus) load();
  }, [clinicalStatus, load]);

  useEffect(() => {
    if (!status || !IN_PROGRESS.includes(status.index_status)) return undefined;
    const timer = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, load]);

  async function run() {
    setStarting(true);
    setError(null);
    try {
      await startIndexing(documentId);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || (status && IN_PROGRESS.includes(status.index_status));
  const ready = clinicalStatus === "completed" || clinicalStatus === "completed_with_errors";

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Evidence index</h2>
        {status && <StatusBadge status={status.index_status} />}
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
      {status && (
        <div className="mt-3 space-y-2 text-sm text-slate-600">
          {status.indexed_count != null && (
            <p>
              {status.indexed_count} evidence item{status.indexed_count === 1 ? "" : "s"} indexed
              {status.index_model && <span className="font-mono text-xs"> ({status.index_model})</span>}.
            </p>
          )}
          {status.stale && (
            <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900">
              Indexed with a different embedding than the one configured now ({status.current_model}); it is not searchable
              until you re-index.
            </p>
          )}
          {status.index_status === "not_processed" && !ready && <p className="text-slate-500">Extract clinical information first.</p>}
          {status.error_message && (
            <div role="alert" className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-rose-900">
              <p className="font-medium">Problem during indexing</p>
              <p className="mt-1 break-words">{status.error_message}</p>
            </div>
          )}
          <p className="text-xs text-slate-500">Search it in the Evidence Explorer tab. Retrieval quality: Not yet evaluated.</p>
        </div>
      )}
      <button
        type="button"
        onClick={run}
        disabled={busy || !status || !ready}
        className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-40"
      >
        {busy ? "Working…" : status?.index_status === "not_processed" ? "Index evidence" : "Re-index"}
      </button>
    </section>
  );
}
