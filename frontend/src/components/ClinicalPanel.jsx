import { useCallback, useEffect, useRef, useState } from "react";
import { getClinicalStatus, startClinical } from "../api/client.js";
import { CLINICAL_NOTE, ENTITY_LABELS, IN_PROGRESS } from "../utils/processing.js";
import StatusBadge from "./StatusBadge.jsx";

const POLL_MS = 1500;

// `onStatus(status)` is called after every fetch; it must be stable (useCallback).
export default function ClinicalPanel({ documentId, textStatus, mmStatus, onStatus }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const currentId = useRef(documentId);

  const load = useCallback(async () => {
    const id = documentId;
    try {
      const next = await getClinicalStatus(id);
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

  // The automatic pipeline runs this stage after the earlier ones: re-check when they change.
  useEffect(() => {
    if (textStatus || mmStatus) load();
  }, [textStatus, mmStatus, load]);

  useEffect(() => {
    if (!status || !IN_PROGRESS.includes(status.clinical_status)) return undefined;
    const timer = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, load]);

  async function run() {
    setStarting(true);
    setError(null);
    try {
      await startClinical(documentId);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || (status && IN_PROGRESS.includes(status.clinical_status));
  const textReady = textStatus === "completed" || textStatus === "completed_with_errors";
  const label = status?.clinical_status === "not_processed" ? "Extract clinical information" : "Run again";
  const counts = status ? Object.entries(status.by_entity_type) : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Clinical information</h2>
        {status && <StatusBadge status={status.clinical_status} />}
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
                Pages analysed: {status.pages_processed} / {status.page_count}
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
          {status.evidence_count != null && (
            <p>
              Found {status.evidence_count} item{status.evidence_count === 1 ? "" : "s"}
              {counts.length > 0 && (
                <span className="text-slate-500">
                  {" "}
                  ({counts.map(([k, n]) => `${n} ${(ENTITY_LABELS[k] ?? k).toLowerCase()}`).join(", ")})
                </span>
              )}
              .
            </p>
          )}
          {status.clinical_status === "not_processed" && !textReady && (
            <p className="text-slate-500">Process the document (text extraction) first.</p>
          )}
          {status.error_message && (
            <div
              role="alert"
              className={`rounded-md border px-3 py-2 ${
                status.clinical_status === "failed"
                  ? "border-rose-300 bg-rose-50 text-rose-900"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              <p className="font-medium">Problem during extraction</p>
              <p className="mt-1 break-words">{status.error_message}</p>
            </div>
          )}
          <p className="text-xs text-slate-500">{CLINICAL_NOTE}</p>
        </div>
      )}

      <button
        type="button"
        onClick={run}
        disabled={busy || !status || !textReady}
        className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-40"
      >
        {busy ? "Working…" : label}
      </button>
    </section>
  );
}
