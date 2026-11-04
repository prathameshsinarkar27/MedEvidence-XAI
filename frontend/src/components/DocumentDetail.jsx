import { useEffect, useState } from "react";
import { getDocument } from "../api/client.js";
import { formatBytes, formatDateTime } from "../utils/format.js";

export default function DocumentDetail({ documentId }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!documentId) return undefined;
    const controller = new AbortController();
    setDoc(null);
    setError(null);
    getDocument(documentId, { signal: controller.signal })
      .then(setDoc)
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [documentId]);

  if (!documentId) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 p-5 text-sm text-slate-500">
        Select a document to see its metadata.
      </section>
    );
  }

  const rows = doc
    ? [
        ["Document ID", doc.id, true],
        ["Original filename", doc.original_filename],
        ["File type", `${doc.file_type} (${doc.mime_type})`],
        ["Size", `${formatBytes(doc.file_size_bytes)} (${doc.file_size_bytes.toLocaleString()} bytes)`],
        ["SHA-256", doc.sha256, true],
        ["Storage location", doc.storage_path, true],
        ["Upload status", doc.upload_status],
        ["Uploaded", formatDateTime(doc.uploaded_at)],
      ]
    : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">Document metadata</h2>
      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-700">
          {error}
        </p>
      )}
      {!doc && !error && <p className="mt-3 text-sm text-slate-500">Loading…</p>}
      {doc && (
        <dl className="mt-3 grid gap-x-4 gap-y-2 text-sm [grid-template-columns:max-content_1fr]">
          {rows.map(([label, value, mono]) => (
            <div key={label} className="contents">
              <dt className="text-slate-500">{label}</dt>
              <dd className={`break-all text-slate-800 ${mono ? "font-mono text-xs leading-5" : ""}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="mt-4 text-xs text-slate-400">
        Text extraction, OCR and clinical analysis are not part of this phase.
      </p>
    </section>
  );
}
