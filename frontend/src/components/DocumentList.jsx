import { formatBytes, formatDateTime } from "../utils/format.js";
import StatusBadge from "./StatusBadge.jsx";

export default function DocumentList({ data, loading, error, selectedId, onSelect, onPage }) {
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const limit = data?.limit ?? 20;
  const offset = data?.offset ?? 0;

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Documents</h2>
        <span className="text-xs text-slate-500">{loading ? "Loading…" : `${total} total`}</span>
      </div>

      {error && (
        <p role="alert" className="px-5 py-4 text-sm text-rose-700">
          {error}
        </p>
      )}

      {!error && !loading && items.length === 0 && (
        <p className="px-5 py-8 text-center text-sm text-slate-500">No documents uploaded yet.</p>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">Pages</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Uploaded</th>
                <th className="px-3 py-2 font-medium">Processing</th>
                <th className="px-3 py-2 font-medium">Tables / images</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((doc) => (
                <tr
                  key={doc.id}
                  onClick={() => onSelect(doc.id)}
                  className={`cursor-pointer hover:bg-slate-50 ${doc.id === selectedId ? "bg-slate-100" : ""}`}
                >
                  <td className="px-5 py-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelect(doc.id);
                      }}
                      className="max-w-xs truncate text-left font-medium text-slate-800 hover:underline"
                      title={doc.original_filename}
                    >
                      {doc.original_filename}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{doc.page_count ?? "—"}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">{formatBytes(doc.file_size_bytes)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">{formatDateTime(doc.uploaded_at)}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={doc.processing_status} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                    {doc.table_count == null ? (
                      <StatusBadge status={doc.multimodal_status} />
                    ) : (
                      `${doc.table_count} / ${doc.image_count}`
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > limit && (
        <div className="flex items-center justify-between border-t border-slate-100 px-5 py-2 text-xs text-slate-500">
          <span>
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <span className="space-x-2">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => onPage(Math.max(0, offset - limit))}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + limit >= total || loading}
              onClick={() => onPage(offset + limit)}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 disabled:opacity-40"
            >
              Next
            </button>
          </span>
        </div>
      )}
    </section>
  );
}
