import { useEffect, useMemo, useRef, useState } from "react";
import { getImage, getTable, imageFileUrl, listImages, listTables } from "../api/client.js";
import { IMAGE_OCR_LABELS, IN_PROGRESS, IMAGE_STATUS_LABELS, TABLE_METHOD_LABELS } from "../utils/processing.js";
import { formatBytes } from "../utils/format.js";
import SourcePreview from "./SourcePreview.jsx";

const pt = (v) => Number(v).toFixed(1);

function SourceInfo({ item }) {
  return (
    <p className="text-xs text-slate-500">
      Source: page {item.page_number}
      {item.page_rotation ? ` (rotated ${item.page_rotation}\u00b0)` : ""}
      {item.bbox && (
        <>
          {" "}
          &middot; region (PDF points) x {pt(item.bbox.x0)}&ndash;{pt(item.bbox.x1)}, y {pt(item.bbox.y0)}&ndash;
          {pt(item.bbox.y1)} on a {pt(item.page_width)} &times; {pt(item.page_height)} page
        </>
      )}
    </p>
  );
}

function TableView({ documentId, table, siblings, onSelect }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    getTable(documentId, table.id, { signal: controller.signal })
      .then(setDetail)
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [documentId, table.id]);

  const boxes = siblings
    .filter((t) => t.page_number === table.page_number)
    .map((t) => ({ id: t.id, region: t.region, label: `Table ${t.table_index}`, active: t.id === table.id }));

  return (
    <div className="space-y-3">
      <SourceInfo item={table} />
      <p className="text-xs text-slate-500">
        {table.row_count} rows &times; {table.col_count} columns &middot;{" "}
        {TABLE_METHOD_LABELS[table.detection_method] ?? table.detection_method}. Cell text is shown as read from the
        PDF; detection has not been evaluated.
      </p>
      {error && (
        <p role="alert" className="text-sm text-rose-700">
          {error}
        </p>
      )}
      {!detail && !error && <p className="text-sm text-slate-500">Loading table…</p>}
      {detail && (
        <div className="max-h-96 overflow-auto rounded-md border border-slate-200">
          <table className="min-w-full border-collapse text-left text-xs" aria-label={`Table ${table.table_index} on page ${table.page_number}`}>
            <tbody>
              {detail.rows.map((row, r) => (
                <tr key={r} className="border-b border-slate-100 last:border-0">
                  {row.map((text, c) =>
                    text === null ? (
                      <td key={c} className="bg-slate-100 px-2 py-1 text-slate-400" title="No cell at this position (merged or missing)">
                        &nbsp;
                      </td>
                    ) : (
                      <td key={c} className="whitespace-pre-wrap border-r border-slate-100 px-2 py-1 font-mono text-slate-800 last:border-r-0">
                        {text}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SourcePreview documentId={documentId} pageNumber={table.page_number} boxes={boxes} onSelectBox={onSelect} />
    </div>
  );
}

function ImageView({ documentId, image, siblings, onSelect, running }) {
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    getImage(documentId, image.id, { signal: controller.signal })
      .then(setDetail)
      .catch(() => {});
    return () => controller.abort();
  }, [documentId, image.id]);

  const boxes = siblings
    .filter((i) => i.page_number === image.page_number && i.region)
    .map((i) => ({ id: i.id, region: i.region, label: `Image ${i.image_index}`, active: i.id === image.id }));

  return (
    <div className="space-y-3">
      <SourceInfo item={image} />
      <dl className="grid gap-x-4 gap-y-1 text-xs [grid-template-columns:max-content_1fr]">
        {[
          ["Size", `${image.width_px} \u00d7 ${image.height_px} px`],
          ["Format", `${image.original_format ?? "unknown"} in the PDF, stored as ${image.stored_format ?? "\u2014"}`],
          ["File size", image.file_size_bytes != null ? formatBytes(image.file_size_bytes) : "\u2014"],
          ["Colour space", image.colorspace ?? "\u2014"],
          ["Status", IMAGE_STATUS_LABELS[image.extraction_status] ?? image.extraction_status],
          ["Image OCR", IMAGE_OCR_LABELS[image.ocr_status] ?? image.ocr_status],
        ].map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="text-slate-800">{v}</dd>
          </div>
        ))}
      </dl>
      {image.is_full_page && (
        <p className="text-xs text-slate-600">Covers (almost) the whole page: probably a scanned page.</p>
      )}
      {image.error_message && (
        <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {image.error_message}
        </p>
      )}
      {running ? (
        <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">Extraction is running; images will reappear when it finishes.</p>
      ) : image.has_file ? (
        <img
          src={imageFileUrl(documentId, image.id)}
          alt={`Embedded image ${image.image_index} from page ${image.page_number}`}
          className="max-h-72 max-w-full rounded-md border border-slate-200 bg-white object-contain"
        />
      ) : (
        <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">No image file is available.</p>
      )}
      {detail?.ocr_text && (
        <div>
          <p className="text-xs font-medium text-slate-600">
            Text read from inside the image
            {detail.ocr_mean_confidence != null && (
              <span title="Tesseract's own mean word confidence. It is not a measured accuracy."> (Tesseract confidence {detail.ocr_mean_confidence})</span>
            )}
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-3 font-mono text-xs text-slate-800">
            {detail.ocr_text}
          </pre>
        </div>
      )}
      <p className="text-xs text-slate-400">
        The image is shown as embedded in the PDF. This system does not interpret image content and gives no medical
        reading of any picture.
      </p>
      {image.region && (
        <SourcePreview documentId={documentId} pageNumber={image.page_number} boxes={boxes} onSelectBox={onSelect} />
      )}
    </div>
  );
}

// `status` is the latest multimodal status; lists reload whenever it changes.
export default function MultimodalViewer({ documentId, status }) {
  const [tab, setTab] = useState("tables");
  const [tables, setTables] = useState([]);
  const [images, setImages] = useState([]);
  const [selectedTable, setSelectedTable] = useState(null);
  const [selectedImage, setSelectedImage] = useState(null);
  const [error, setError] = useState(null);
  const userChoseTab = useRef(false);

  const refreshKey = `${status?.multimodal_status}:${status?.pages_processed}`;

  useEffect(() => {
    setTables([]);
    setImages([]);
    setSelectedTable(null);
    setSelectedImage(null);
    setTab("tables");
    userChoseTab.current = false;
  }, [documentId]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listTables(documentId, { signal: controller.signal }), listImages(documentId, { signal: controller.signal })])
      .then(([t, i]) => {
        setTables(t.items);
        setImages(i.items);
        setError(null);
        // Until the user picks a tab, show whichever kind of item the document actually has.
        if (!userChoseTab.current) setTab(t.items.length === 0 && i.items.length > 0 ? "images" : "tables");
      })
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [documentId, refreshKey]);

  const table = useMemo(() => tables.find((t) => t.id === selectedTable) ?? tables[0] ?? null, [tables, selectedTable]);
  const image = useMemo(() => images.find((i) => i.id === selectedImage) ?? images[0] ?? null, [images, selectedImage]);

  const tabs = [
    ["tables", `Tables (${tables.length})`],
    ["images", `Images (${images.length})`],
  ];

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Tables &amp; images by source page</h2>
        <div role="tablist" aria-label="Tables or images" className="flex gap-1">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => {
                userChoseTab.current = true;
                setTab(id);
              }}
              className={`rounded px-3 py-1 text-xs font-medium ${
                tab === id ? "bg-slate-900 text-white" : "border border-slate-300 hover:bg-slate-100"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p role="alert" className="px-5 py-3 text-sm text-rose-700">
          {error}
        </p>
      )}

      {tab === "tables" && tables.length === 0 && !error && (
        <p className="px-5 py-8 text-center text-sm text-slate-500">
          No tables found yet. Run table &amp; image extraction, or this document has no detectable tables.
        </p>
      )}
      {tab === "tables" && table && (
        <div className="grid gap-0 md:grid-cols-[11rem_1fr]">
          <ul className="max-h-[34rem] overflow-auto border-b border-slate-100 md:border-b-0 md:border-r" aria-label="Tables">
            {tables.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setSelectedTable(t.id)}
                  aria-current={t.id === table.id ? "true" : undefined}
                  className={`block w-full px-4 py-2 text-left text-sm hover:bg-slate-50 ${t.id === table.id ? "bg-slate-100 font-medium" : ""}`}
                >
                  Page {t.page_number} &middot; Table {t.table_index}
                  <span className="block text-xs font-normal text-slate-500">
                    {t.row_count} &times; {t.col_count}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-w-0 p-5">
            <TableView documentId={documentId} table={table} siblings={tables} onSelect={setSelectedTable} />
          </div>
        </div>
      )}

      {tab === "images" && images.length === 0 && !error && (
        <p className="px-5 py-8 text-center text-sm text-slate-500">
          No embedded images found yet. Run table &amp; image extraction, or this document has none.
        </p>
      )}
      {tab === "images" && image && (
        <div className="grid gap-0 md:grid-cols-[11rem_1fr]">
          <ul className="max-h-[34rem] overflow-auto border-b border-slate-100 md:border-b-0 md:border-r" aria-label="Images">
            {images.map((i) => (
              <li key={i.id}>
                <button
                  type="button"
                  onClick={() => setSelectedImage(i.id)}
                  aria-current={i.id === image.id ? "true" : undefined}
                  className={`block w-full px-4 py-2 text-left text-sm hover:bg-slate-50 ${i.id === image.id ? "bg-slate-100 font-medium" : ""}`}
                >
                  Page {i.page_number} &middot; Image {i.image_index}
                  <span className="block text-xs font-normal text-slate-500">
                    {i.width_px} &times; {i.height_px} px{i.extraction_status === "failed" ? " \u00b7 not extracted" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-w-0 p-5">
            <ImageView
              documentId={documentId}
              image={image}
              siblings={images}
              onSelect={setSelectedImage}
              running={IN_PROGRESS.includes(status?.multimodal_status)}
            />
          </div>
        </div>
      )}
    </section>
  );
}
