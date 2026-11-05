import { useEffect, useMemo, useState } from "react";
import { listClinicalEvidence } from "../api/client.js";
import {
  ASSERTION_LABELS,
  CLINICAL_NOTE,
  ENTITY_LABELS,
  FLAG_LABELS,
  FLAG_SOURCE_LABELS,
  IN_PROGRESS,
  MODALITY_LABELS,
} from "../utils/processing.js";
import SourcePreview from "./SourcePreview.jsx";

const TABS = [
  ["lab_result", "Lab results", ["lab_result"]],
  ["vital_sign", "Vital signs", ["vital_sign"]],
  ["medication", "Medications", ["medication"]],
  ["finding", "Findings", ["condition", "symptom"]],
  ["date", "Dates", ["date"]],
  ["all", "All", null],
];

function valueText(item) {
  if (item.entity_type === "date") return item.date_iso ?? `${item.date_text} (ambiguous)`;
  if (item.value_text == null) return "—";
  const unit = item.unit_text && !item.value_text.includes(item.unit_text) ? ` ${item.unit_text}` : ""; // dose text already has its unit
  return `${item.value_comparator ?? ""}${item.value_text}${unit}`;
}

function Pill({ children, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    amber: "bg-amber-100 text-amber-900",
    rose: "bg-rose-100 text-rose-800",
    sky: "bg-sky-100 text-sky-800",
  };
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

function assertionTone(assertion) {
  return assertion === "affirmed" ? "slate" : assertion === "negated" ? "rose" : "amber";
}

// The sentence with the exact mention highlighted (offsets are relative to the stored page text).
function SourceSentence({ item }) {
  const { source_text: text, mention_text: mention, char_start: cs, source_start: ss } = item;
  const offset = cs != null && ss != null ? cs - ss : text.indexOf(mention);
  if (offset == null || offset < 0 || text.slice(offset, offset + mention.length) !== mention) {
    return <span className="whitespace-pre-wrap">{text}</span>;
  }
  return (
    <span className="whitespace-pre-wrap">
      {text.slice(0, offset)}
      <mark className="rounded bg-amber-200 px-0.5">{mention}</mark>
      {text.slice(offset + mention.length)}
    </span>
  );
}

function Detail({ documentId, item, pageItems, onSelect }) {
  const attrs = Object.entries(item.attributes ?? {});
  const factors = Object.entries(item.confidence_factors ?? {});
  const boxes = pageItems
    .filter((e) => e.region)
    .map((e) => ({
      id: e.evidence_id,
      region: e.region,
      label: `${ENTITY_LABELS[e.entity_type]}: ${e.entity_name}`,
      active: e.evidence_id === item.evidence_id,
    }));
  return (
    <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
      <div className="space-y-3 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Source text</p>
          <p className="mt-1 rounded-md border border-slate-200 bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
            <SourceSentence item={item} />
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Page {item.page_number} &middot; {MODALITY_LABELS[item.modality] ?? item.modality}
            {item.table_row_index != null && ` · table row ${item.table_row_index + 1}`}
            {item.char_start != null && ` · characters ${item.char_start}–${item.char_end}`}
          </p>
        </div>
        <dl className="grid gap-x-4 gap-y-1 text-xs [grid-template-columns:max-content_1fr]">
          <dt className="text-slate-500">Name (normalised)</dt>
          <dd className="text-slate-800">{item.entity_name}</dd>
          <dt className="text-slate-500">As written</dt>
          <dd className="break-all font-mono text-slate-800">{item.mention_text}</dd>
          <dt className="text-slate-500">Assertion</dt>
          <dd className="text-slate-800">{ASSERTION_LABELS[item.assertion] ?? item.assertion}</dd>
          {item.value_text != null && (
            <>
              <dt className="text-slate-500">Value</dt>
              <dd className="text-slate-800">
                {item.value_comparator ?? ""}
                {item.value_text}
                {item.unit_text && !item.value_text.includes(item.unit_text) && (
                  <>
                    {" "}
                    {item.unit_text}
                  </>
                )}
                {item.unit_normalized && item.unit_normalized !== item.unit_text && (
                  <span className="text-slate-500"> (unit normalised: {item.unit_normalized})</span>
                )}
              </dd>
            </>
          )}
          {item.reference_text && (
            <>
              <dt className="text-slate-500">Reference range</dt>
              <dd className="text-slate-800">{item.reference_text} (as printed)</dd>
            </>
          )}
          {item.abnormal_flag && (
            <>
              <dt className="text-slate-500">Flag</dt>
              <dd className="text-slate-800">
                {FLAG_LABELS[item.abnormal_flag]} &mdash; {FLAG_SOURCE_LABELS[item.flag_source] ?? item.flag_source}
              </dd>
            </>
          )}
          {item.date_text && (
            <>
              <dt className="text-slate-500">Date</dt>
              <dd className="text-slate-800">
                {item.date_text} {item.date_iso ? `→ ${item.date_iso}` : "(ambiguous: not normalised)"}
              </dd>
            </>
          )}
          {attrs.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
              <dd className="break-all text-slate-800">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
          <dt className="text-slate-500">Method</dt>
          <dd className="text-slate-800">
            {item.extraction_method} (v{item.extractor_version})
          </dd>
          <dt className="text-slate-500">Confidence</dt>
          <dd className="text-slate-800">
            {item.extraction_confidence.toFixed(2)} <span className="text-slate-500">(heuristic score, not a probability)</span>
          </dd>
        </dl>
        {factors.length > 0 && (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer">How the score was built</summary>
            <ul className="mt-1 list-disc pl-5">
              {factors.map(([k, v]) => (
                <li key={k}>
                  {k.replace(/_/g, " ")}: {v > 0 && k !== "base" && !k.includes("multiplier") ? "+" : ""}
                  {v}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <div>
        {item.region ? (
          <SourcePreview documentId={documentId} pageNumber={item.page_number} boxes={boxes} onSelectBox={onSelect} />
        ) : (
          <p className="rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-500">
            No page region is available for this item (for example it came from OCR text, which has no stored word
            positions). The page number and exact source text above still identify where it was found.
          </p>
        )}
      </div>
    </div>
  );
}

export default function ClinicalViewer({ documentId, status }) {
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("lab_result");
  const [selectedId, setSelectedId] = useState(null);
  const [minConfidence, setMinConfidence] = useState(0);

  const state = status?.clinical_status;
  const running = state && IN_PROGRESS.includes(state);
  const version = `${state}|${status?.evidence_count}|${status?.processed_at}`;

  useEffect(() => {
    setItems(null);
    setSelectedId(null);
    setError(null);
    setTab("lab_result");
  }, [documentId]);

  useEffect(() => {
    if (!state || state === "not_processed" || running) {
      if (state === "not_processed") setItems([]);
      return undefined;
    }
    const controller = new AbortController();
    listClinicalEvidence(documentId, {}, { signal: controller.signal })
      .then((body) => {
        setItems(body.items);
        setTotal(body.total);
        setError(null);
      })
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [documentId, version, state, running]);

  const counts = useMemo(() => {
    const result = {};
    for (const [key, , types] of TABS) result[key] = (items ?? []).filter((i) => !types || types.includes(i.entity_type)).length;
    return result;
  }, [items]);

  // Open the first tab that has content once results arrive.
  useEffect(() => {
    if (!items || items.length === 0) return;
    setTab((current) => (counts[current] > 0 ? current : (TABS.find(([key]) => key !== "all" && counts[key] > 0)?.[0] ?? "all")));
  }, [items, counts]);

  const types = TABS.find(([key]) => key === tab)?.[2];
  const visible = (items ?? []).filter(
    (i) => (!types || types.includes(i.entity_type)) && i.extraction_confidence >= minConfidence,
  );
  const selected = visible.find((i) => i.evidence_id === selectedId) ?? null;
  const pageItems = selected ? (items ?? []).filter((i) => i.page_number === selected.page_number) : [];

  if (!status || status.clinical_status === "not_processed") {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 p-5 text-sm text-slate-500">
        Clinical information appears here after extraction runs.
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">Extracted clinical information</h2>
      <p className="mt-1 text-xs text-slate-500">{CLINICAL_NOTE}</p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-700">
          {error}
        </p>
      )}
      {running && <p className="mt-3 text-sm text-slate-500">Extraction is running…</p>}
      {items && items.length === 0 && !running && (
        <p className="mt-3 text-sm text-slate-500">
          Nothing was found. The extractor only reports terms from its built-in vocabulary and patterns it recognises.
        </p>
      )}
      {items && items.length > 0 && (
        <>
          {total > items.length && (
            <p className="mt-2 text-xs text-amber-800">
              Showing the first {items.length} of {total} items.
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" className="flex flex-wrap gap-1">
              {TABS.map(([key, label]) => (
                <button
                  type="button"
                  role="tab"
                  key={key}
                  aria-selected={tab === key}
                  onClick={() => {
                    setTab(key);
                    setSelectedId(null);
                  }}
                  className={`rounded-md px-3 py-1 text-sm ${
                    tab === key ? "bg-slate-800 text-white" : "border border-slate-300 text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  {label} ({counts[key]})
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-600">
              Min. confidence {minConfidence.toFixed(2)}
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={minConfidence}
                onChange={(e) => setMinConfidence(Number(e.target.value))}
                aria-label="Minimum confidence"
              />
            </label>
          </div>

          <div className="mt-3 max-h-80 overflow-auto rounded-md border border-slate-200">
            <table className="min-w-full border-collapse text-left text-xs" aria-label="Extracted clinical items">
              <thead className="sticky top-0 bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Type</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Value</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Page</th>
                  <th className="px-2 py-1.5 font-medium">Source</th>
                  <th className="px-2 py-1.5 font-medium">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr
                    key={item.evidence_id}
                    onClick={() => setSelectedId(item.evidence_id === selectedId ? null : item.evidence_id)}
                    className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                      item.evidence_id === selectedId ? "bg-sky-50" : ""
                    }`}
                  >
                    <td className="px-2 py-1.5 text-slate-600">{ENTITY_LABELS[item.entity_type]}</td>
                    <td className="px-2 py-1.5 font-medium text-slate-800">
                      <button
                        type="button"
                        className="text-left underline-offset-2 hover:underline"
                        aria-label={`Show source of ${item.entity_name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedId(item.evidence_id === selectedId ? null : item.evidence_id);
                        }}
                      >
                        {item.entity_name}
                      </button>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-slate-800">
                      {valueText(item)}{" "}
                      {item.abnormal_flag && item.abnormal_flag !== "normal" && (
                        <Pill tone="amber">{FLAG_LABELS[item.abnormal_flag]}</Pill>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <Pill tone={assertionTone(item.assertion)}>{ASSERTION_LABELS[item.assertion] ?? item.assertion}</Pill>
                    </td>
                    <td className="px-2 py-1.5 text-slate-600">{item.page_number}</td>
                    <td className="px-2 py-1.5 text-slate-600">{MODALITY_LABELS[item.modality] ?? item.modality}</td>
                    <td className="px-2 py-1.5 font-mono text-slate-700">{item.extraction_confidence.toFixed(2)}</td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-2 py-3 text-slate-500">
                      No items match.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4">
            {selected ? (
              <Detail documentId={documentId} item={selected} pageItems={pageItems} onSelect={setSelectedId} />
            ) : (
              <p className="text-xs text-slate-500">Select an item to see its exact source text and where it sits on the page.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
