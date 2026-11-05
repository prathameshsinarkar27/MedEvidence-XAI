import { useCallback, useEffect, useRef, useState } from "react";
import { getDocument } from "../api/client.js";
import { formatBytes, formatDateTime } from "../utils/format.js";
import ProcessingPanel from "./ProcessingPanel.jsx";
import PageViewer from "./PageViewer.jsx";
import MultimodalPanel from "./MultimodalPanel.jsx";
import MultimodalViewer from "./MultimodalViewer.jsx";
import ClinicalPanel from "./ClinicalPanel.jsx";
import ClinicalViewer from "./ClinicalViewer.jsx";

// `onProcessingChange` fires when the document's processing status changes (so the list can refresh).
export default function DocumentDetail({ documentId, onProcessingChange }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [mmStatus, setMmStatus] = useState(null);
  const [clinicalStatus, setClinicalStatus] = useState(null);
  const lastClinicalStatus = useRef(null);
  const lastStatus = useRef(null);
  const lastMmStatus = useRef(null);

  useEffect(() => {
    if (!documentId) return undefined;
    const controller = new AbortController();
    setDoc(null);
    setError(null);
    setStatus(null);
    setMmStatus(null);
    setClinicalStatus(null);
    lastClinicalStatus.current = null;
    lastStatus.current = null;
    lastMmStatus.current = null;
    getDocument(documentId, { signal: controller.signal })
      .then(setDoc)
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [documentId]);

  const handleStatus = useCallback(
    (next) => {
      setStatus(next);
      if (lastStatus.current !== null && lastStatus.current !== next.processing_status) {
        onProcessingChange?.();
        // page count / PDF info become known once processing starts; refresh the metadata panel
        getDocument(next.document_id).then(setDoc).catch(() => {});
      }
      lastStatus.current = next.processing_status;
    },
    [onProcessingChange],
  );

  const handleMmStatus = useCallback(
    (next) => {
      setMmStatus(next);
      if (lastMmStatus.current !== null && lastMmStatus.current !== next.multimodal_status) {
        onProcessingChange?.();
        getDocument(next.document_id).then(setDoc).catch(() => {}); // refresh the table/image counts
      }
      lastMmStatus.current = next.multimodal_status;
    },
    [onProcessingChange],
  );

  const handleClinicalStatus = useCallback(
    (next) => {
      setClinicalStatus(next);
      if (lastClinicalStatus.current !== null && lastClinicalStatus.current !== next.clinical_status) {
        onProcessingChange?.();
        getDocument(next.document_id).then(setDoc).catch(() => {}); // refresh the evidence count
      }
      lastClinicalStatus.current = next.clinical_status;
    },
    [onProcessingChange],
  );

  if (!documentId) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 p-5 text-sm text-slate-500">
        Select a document to see its metadata and extracted text.
      </section>
    );
  }

  const rows = doc
    ? [
        ["Document ID", doc.id, true],
        ["Original filename", doc.original_filename],
        ["File type", `${doc.file_type} (${doc.mime_type})`],
        ["Size", `${formatBytes(doc.file_size_bytes)} (${doc.file_size_bytes.toLocaleString()} bytes)`],
        ["Pages", doc.page_count ?? "—"],
        ["SHA-256", doc.sha256, true],
        ["Storage location", doc.storage_path, true],
        ["Upload status", doc.upload_status],
        ["Uploaded", formatDateTime(doc.uploaded_at)],
        ["Processed", formatDateTime(doc.processed_at)],
        ["Tables / images", doc.table_count == null ? "\u2014" : `${doc.table_count} / ${doc.image_count}`],
        ["Clinical items", doc.evidence_count == null ? "\u2014" : doc.evidence_count],
      ]
    : [];
  const pdfInfo = Object.entries(doc?.pdf_metadata ?? {});

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
      <div className="space-y-6">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700">Document details</h2>
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
          {pdfInfo.length > 0 && (
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-slate-600">PDF information ({pdfInfo.length})</summary>
              <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs [grid-template-columns:max-content_1fr]">
                {pdfInfo.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="text-slate-500">{key}</dt>
                    <dd className="break-all text-slate-800">{value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </section>
        <ProcessingPanel documentId={documentId} onStatus={handleStatus} />
        <MultimodalPanel documentId={documentId} textStatus={status?.processing_status} onStatus={handleMmStatus} />
        <ClinicalPanel
          documentId={documentId}
          textStatus={status?.processing_status}
          mmStatus={mmStatus?.multimodal_status}
          onStatus={handleClinicalStatus}
        />
      </div>
      <PageViewer documentId={documentId} status={status} />
      <div className="lg:col-span-2">
        <MultimodalViewer documentId={documentId} status={mmStatus} />
      </div>
      <div className="lg:col-span-2">
        <ClinicalViewer documentId={documentId} status={clinicalStatus} />
      </div>
    </div>
  );
}
