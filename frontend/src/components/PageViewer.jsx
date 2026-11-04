import { useEffect, useState } from "react";
import { getPage, listPages } from "../api/client.js";
import { METHOD_LABELS, PAGE_DOT, PAGE_STATUS_LABELS } from "../utils/processing.js";

// `status` is the latest processing status; the page list reloads whenever it changes.
export default function PageViewer({ documentId, status }) {
  const [pages, setPages] = useState([]);
  const [selected, setSelected] = useState(1);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  const refreshKey = `${status?.processing_status}:${status?.pages_processed}`;

  useEffect(() => {
    setSelected(1);
    setDetail(null);
    setPages([]);
  }, [documentId]);

  useEffect(() => {
    const controller = new AbortController();
    listPages(documentId, { signal: controller.signal })
      .then((data) => {
        setPages(data.items);
        setError(null);
      })
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [documentId, refreshKey]);

  const available = pages.some((p) => p.page_number === selected);
  useEffect(() => {
    if (!available) {
      setDetail(null);
      return undefined;
    }
    const controller = new AbortController();
    getPage(documentId, selected, { signal: controller.signal })
      .then((data) => {
        setDetail(data);
        setError(null);
      })
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [documentId, selected, available, refreshKey]);

  const total = pages.length;

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Extracted text by page</h2>
        {total > 0 && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <button
              type="button"
              onClick={() => setSelected((n) => Math.max(1, n - 1))}
              disabled={selected <= 1}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 disabled:opacity-40"
            >
              Previous
            </button>
            <span>
              Page {selected} of {total}
            </span>
            <button
              type="button"
              onClick={() => setSelected((n) => Math.min(total, n + 1))}
              disabled={selected >= total}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="px-5 py-3 text-sm text-rose-700">
          {error}
        </p>
      )}

      {total === 0 && !error && (
        <p className="px-5 py-8 text-center text-sm text-slate-500">
          No pages yet. Run text extraction to see page-level content.
        </p>
      )}

      {total > 0 && (
        <div className="grid gap-0 md:grid-cols-[9rem_1fr]">
          <ul className="max-h-[28rem] overflow-auto border-b border-slate-100 md:border-b-0 md:border-r" aria-label="Pages">
            {pages.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setSelected(p.page_number)}
                  aria-current={p.page_number === selected ? "true" : undefined}
                  className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 ${
                    p.page_number === selected ? "bg-slate-100 font-medium" : ""
                  }`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${PAGE_DOT[p.processing_status] ?? "bg-slate-400"}`} />
                  Page {p.page_number}
                  {p.extraction_method === "ocr_tesseract" && (
                    <span className="ml-auto rounded bg-slate-200 px-1 text-[10px] font-semibold">OCR</span>
                  )}
                </button>
              </li>
            ))}
          </ul>

          <div className="min-w-0 p-5">
            {detail ? (
              <>
                <dl className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
                  <div>
                    <dt className="inline">Source: </dt>
                    <dd className="inline text-slate-700">{METHOD_LABELS[detail.extraction_method] ?? detail.extraction_method}</dd>
                  </div>
                  <div>
                    <dt className="inline">Characters: </dt>
                    <dd className="inline text-slate-700">{detail.char_count.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt className="inline">Status: </dt>
                    <dd className="inline text-slate-700">{PAGE_STATUS_LABELS[detail.processing_status] ?? detail.processing_status}</dd>
                  </div>
                  {detail.is_likely_scanned && <div className="text-slate-700">Likely a scanned page</div>}
                  {detail.ocr_mean_confidence != null && (
                    <div title="Tesseract's own mean word confidence. It is not a measured accuracy.">
                      <dt className="inline">OCR word confidence (Tesseract): </dt>
                      <dd className="inline text-slate-700">{detail.ocr_mean_confidence}</dd>
                    </div>
                  )}
                </dl>

                {detail.error_message && (
                  <p role="alert" className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    {detail.error_message}
                  </p>
                )}

                {detail.extracted_text ? (
                  <pre
                    tabIndex={0}
                    aria-label={`Extracted text of page ${detail.page_number}`}
                    className="max-h-[26rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-800"
                  >
                    {detail.extracted_text}
                  </pre>
                ) : (
                  <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">No text was extracted from this page.</p>
                )}
                <p className="mt-2 text-xs text-slate-400">
                  Shown exactly as extracted. OCR output can contain recognition errors; accuracy has not been evaluated.
                </p>
              </>
            ) : (
              <p className="text-sm text-slate-500">{error ? "" : "Loading…"}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
