import { useCallback, useEffect, useMemo, useState } from "react";
import { browseEvidence, getRankingConfig, hybridSearch, listDocuments, searchEvidence } from "../api/client.js";
import { ASSERTION_LABELS, ENTITY_LABELS, INDEX_NOTE, MODALITY_LABELS } from "../utils/processing.js";
import SourcePreview from "./SourcePreview.jsx";

const MIN_CONF_STEP = 0.05;

function Select({ label, value, onChange, options }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-600">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800">
        <option value="">Any</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  );
}

function valueText(e) {
  if (e.entity_type === "date") return e.date_iso ?? e.date_text ?? "—";
  if (e.value_text == null) return "—";
  const unit = e.unit_text && !e.value_text.includes(e.unit_text) ? ` ${e.unit_text}` : "";
  return `${e.value_comparator ?? ""}${e.value_text}${unit}`;
}

function SourceSentence({ item }) {
  const { source_text: text, mention_text: mention, char_start: cs, source_start: ss } = item;
  const offset = cs != null && ss != null ? cs - ss : text.indexOf(mention);
  if (offset == null || offset < 0 || text.slice(offset, offset + mention.length) !== mention) return <>{text}</>;
  return (
    <>
      {text.slice(0, offset)}
      <mark className="rounded bg-amber-200 px-0.5">{mention}</mark>
      {text.slice(offset + mention.length)}
    </>
  );
}

const COMPONENT_LABELS = {
  semantic: "Semantic", keyword: "Keyword", entity: "Entity", temporal: "Temporal", confidence: "Confidence", source: "Source",
};

function Breakdown({ hit }) {
  if (!hit.components) return null;
  return (
    <div className="text-xs">
      <p className="uppercase tracking-wide text-slate-500">Why this rank (score × weight = contribution)</p>
      <table className="mt-1 w-full border-collapse">
        <tbody>
          {Object.entries(hit.components).map(([name, c]) => (
            <tr key={name} className={c.contribution > 0 ? "text-slate-800" : "text-slate-400"}>
              <td className="py-0.5 pr-2">{COMPONENT_LABELS[name]}</td>
              <td className="w-24 pr-2">
                <span className="block h-1.5 overflow-hidden rounded bg-slate-100">
                  <span className="block h-full bg-sky-500" style={{ width: `${c.score * 100}%` }} />
                </span>
              </td>
              <td className="whitespace-nowrap pr-2 font-mono">{c.score.toFixed(2)} × {c.weight}</td>
              <td className="text-right font-mono">{c.contribution.toFixed(3)}</td>
            </tr>
          ))}
          <tr className="border-t border-slate-200 font-medium text-slate-800">
            <td colSpan={3} className="pt-1">Final score (orders results; not a probability)</td>
            <td className="pt-1 text-right font-mono">{hit.final_score.toFixed(3)}</td>
          </tr>
        </tbody>
      </table>
      {hit.matched_terms?.length > 0 && <p className="mt-1 text-slate-600">Matched words: {hit.matched_terms.join(", ")}</p>}
      {hit.temporal_note && <p className="mt-1 text-slate-600">Date: {hit.temporal_note}</p>}
    </div>
  );
}

function Result({ hit, open, onToggle }) {
  const e = hit.evidence;
  const score = hit.final_score ?? hit.score;
  return (
    <li className="rounded-md border border-slate-200 bg-white">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-slate-50">
        {score != null && (
          <span className="w-14 shrink-0 text-xs text-slate-500" title={hit.components ? "Weighted sum of the component scores. Orders results; not a probability." : "Cosine similarity between the query and this evidence text. Not a probability."}>
            <span className="block font-mono text-slate-800">{score.toFixed(3)}</span>
            <span className="mt-1 block h-1 overflow-hidden rounded bg-slate-100">
              <span className="block h-full bg-sky-500" style={{ width: `${Math.max(0, Math.min(1, hit.components ? score / (hit.maxScore || 1) : score)) * 100}%` }} />
            </span>
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-800">{e.entity_name}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{ENTITY_LABELS[e.entity_type]}</span>
            {e.assertion !== "affirmed" && (
              <span className={`rounded-full px-2 py-0.5 text-xs ${e.assertion === "negated" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-900"}`}>
                {ASSERTION_LABELS[e.assertion]}
              </span>
            )}
            <span className="font-mono text-xs text-slate-700">{valueText(e)}</span>
          </span>
          <span className="mt-0.5 block truncate text-xs text-slate-500">
            {e.document_filename} &middot; page {e.page_number} &middot; {MODALITY_LABELS[e.modality] ?? e.modality} &middot; confidence {e.extraction_confidence.toFixed(2)}
          </span>
        </span>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-slate-100 p-3 lg:grid-cols-[3fr_2fr]">
          <div className="space-y-3 text-xs">
            <div>
              <p className="uppercase tracking-wide text-slate-500">Source text</p>
              <p className="mt-1 whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-2 font-mono leading-5 text-slate-800"><SourceSentence item={e} /></p>
            </div>
            <dl className="grid gap-x-4 gap-y-1 [grid-template-columns:max-content_1fr]">
              <dt className="text-slate-500">Provenance</dt>
              <dd className="text-slate-800">
                {e.document_filename} &rarr; page {e.page_number}
                {e.table_row_index != null && ` → table row ${e.table_row_index + 1}`}
                {e.image_id && " → embedded image"}
                {e.char_start != null && ` → characters ${e.char_start}–${e.char_end}`}
              </dd>
              <dt className="text-slate-500">Evidence ID</dt>
              <dd className="break-all font-mono text-slate-800">{e.evidence_id}</dd>
              <dt className="text-slate-500">Extraction</dt>
              <dd className="text-slate-800">{e.extraction_method} (heuristic confidence {e.extraction_confidence.toFixed(2)}, not a probability)</dd>
            </dl>
            <Breakdown hit={hit} />
            {hit.embedding_text !== undefined && hit.embedding_text && (
              <details className="text-slate-600">
                <summary className="cursor-pointer">Text that was embedded for this item</summary>
                <p className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-2 font-mono text-slate-700">{hit.embedding_text}</p>
              </details>
            )}
          </div>
          <div>
            {e.region ? (
              <SourcePreview
                documentId={e.document_id}
                pageNumber={e.page_number}
                boxes={[{ id: e.evidence_id, region: e.region, label: `${e.entity_name}`, active: true }]}
              />
            ) : (
              <p className="rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-500">
                No page region is stored for this item (for example OCR text has no word positions). The document, page and exact source text still identify it.
              </p>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export default function EvidenceExplorer() {
  const [docs, setDocs] = useState([]);
  const [q, setQ] = useState("");
  const [f, setF] = useState({ document_id: "", entity_type: "", modality: "", assertion: "" });
  const [minConf, setMinConf] = useState(0);
  const [topK, setTopK] = useState(10);
  const [mode, setMode] = useState("hybrid"); // hybrid | semantic (Phase 6 similarity only)
  const [dates, setDates] = useState({ date_from: "", date_to: "" });
  const [config, setConfig] = useState(null);
  const [weights, setWeights] = useState({});
  const [result, setResult] = useState(null); // { mode, hits|items, meta }
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    const c = new AbortController();
    listDocuments({ limit: 100 }, { signal: c.signal }).then((b) => setDocs(b.items)).catch(() => {});
    getRankingConfig({ signal: c.signal }).then(setConfig).catch(() => {});
    return () => c.abort();
  }, []);

  const filterParams = useMemo(
    () => ({ ...f, min_confidence: minConf > 0 ? minConf : undefined }),
    [f, minConf],
  );

  const run = useCallback(async (e) => {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    setOpenId(null);
    try {
      if (q.trim() && mode === "hybrid") {
        const w = Object.fromEntries(Object.entries(weights).map(([k, v]) => [`w_${k}`, v]));
        const body = await hybridSearch({ q: q.trim(), top_k: topK, ...filterParams, ...dates, ...w });
        const maxScore = Math.max(...body.hits.map((h) => h.final_score), 1e-9);
        setResult({ mode: "hybrid", hits: body.hits.map((h) => ({ ...h, maxScore })), meta: body });
      } else if (q.trim()) {
        const body = await searchEvidence({ q: q.trim(), top_k: topK, ...filterParams });
        setResult({ mode: "search", hits: body.hits, meta: body });
      } else {
        const body = await browseEvidence({ limit: 100, ...filterParams });
        setResult({ mode: "browse", hits: body.items.map((evidence) => ({ evidence, score: null, embedding_text: "" })), meta: body });
      }
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [q, topK, filterParams, mode, dates, weights]);

  const meta = result?.meta;
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Evidence Explorer</h2>
        <p className="mt-1 text-xs text-slate-500">
          Search the clinical evidence extracted from your uploaded documents. Leave the query empty to browse by filters.
          {" "}{INDEX_NOTE}
        </p>
        <form onSubmit={run} className="mt-4 space-y-3">
          <div className="flex gap-2">
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              maxLength={500}
              placeholder="e.g. HbA1c, chest pain, metformin dose"
              aria-label="Search query"
              className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
            <button type="submit" disabled={loading} className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50">
              {loading ? "Searching…" : q.trim() ? "Search" : "Browse"}
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Select label="Document" value={f.document_id} onChange={(v) => setF({ ...f, document_id: v })} options={docs.map((d) => [d.id, d.original_filename])} />
            <Select label="Type" value={f.entity_type} onChange={(v) => setF({ ...f, entity_type: v })} options={Object.entries(ENTITY_LABELS)} />
            <Select label="Source" value={f.modality} onChange={(v) => setF({ ...f, modality: v })} options={Object.entries(MODALITY_LABELS)} />
            <Select label="Status" value={f.assertion} onChange={(v) => setF({ ...f, assertion: v })} options={Object.entries(ASSERTION_LABELS)} />
          </div>
          <div className="flex flex-wrap items-center gap-6 text-xs text-slate-600">
            <label className="flex items-center gap-2">
              Ranking
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1" aria-label="Ranking mode">
                <option value="hybrid">Hybrid (semantic + keyword + entity + date…)</option>
                <option value="semantic">Similarity only (Phase 6)</option>
              </select>
            </label>
            {mode === "hybrid" && (
              <>
                <label className="flex items-center gap-2">From <input type="date" value={dates.date_from} onChange={(e) => setDates({ ...dates, date_from: e.target.value })} className="rounded-md border border-slate-300 px-2 py-1" aria-label="Evidence date from" /></label>
                <label className="flex items-center gap-2">To <input type="date" value={dates.date_to} onChange={(e) => setDates({ ...dates, date_to: e.target.value })} className="rounded-md border border-slate-300 px-2 py-1" aria-label="Evidence date to" /></label>
              </>
            )}
            <label className="flex items-center gap-2">
              Min. extraction confidence {minConf.toFixed(2)}
              <input type="range" min="0" max="1" step={MIN_CONF_STEP} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} aria-label="Minimum extraction confidence" />
            </label>
            <label className="flex items-center gap-2">
              Results
              <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} className="rounded-md border border-slate-300 bg-white px-2 py-1">
                {[5, 10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
          {mode === "hybrid" && config && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer">Ranking formula and weights</summary>
              <p className="mt-2 font-mono text-slate-800">{config.formula}</p>
              <p className="mt-1 text-slate-500">Weights are configuration, not truth (see docs/evaluation-retrieval.md). Blank = server default.</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {config.components.map((c) => (
                  <label key={c} className="flex flex-col gap-0.5" title={config.descriptions[c]}>
                    <span className="font-medium text-slate-700">{COMPONENT_LABELS[c]} <span className="font-normal text-slate-400">(default {config.weights[c]})</span></span>
                    <input type="number" min="0" max="100" step="0.05" value={weights[c] ?? ""} placeholder={String(config.weights[c])}
                      onChange={(e) => setWeights({ ...weights, [c]: e.target.value === "" ? undefined : Number(e.target.value) })}
                      className="rounded-md border border-slate-300 px-2 py-1" aria-label={`Weight ${c}`} />
                    <span className="text-slate-400">{config.descriptions[c]}</span>
                  </label>
                ))}
              </div>
            </details>
          )}
        </form>
      </section>

      {error && <p role="alert" className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">{error}</p>}

      {result && (
        <section aria-label="Results" className="space-y-2">
          <p className="text-xs text-slate-500">
            {result.mode === "hybrid"
              ? `${meta.returned} result${meta.returned === 1 ? "" : "s"} · hybrid ranking · ${meta.candidates} candidates · entities understood: ${meta.analysis.entities.join(", ") || "none"}${meta.analysis.periods.length ? ` · date: ${meta.analysis.periods.map((p) => (p[0] === p[1] ? p[0] : `${p[0]}…${p[1]}`)).join(" / ")}` : ""}${meta.analysis.recency ? ` · ${meta.analysis.recency} first` : ""}`
              : result.mode === "search"
              ? `${meta.returned} result${meta.returned === 1 ? "" : "s"} · embedding ${meta.embedding_model} (${meta.is_semantic ? "semantic" : "lexical: matches words, not meaning"}) · ${meta.vector_backend}${meta.candidates != null ? ` · ${meta.candidates} items matched the filters` : ""}`
              : `${meta.total} evidence item${meta.total === 1 ? "" : "s"}${meta.total > result.hits.length ? ` (showing ${result.hits.length})` : ""} · filter-only browse, no ranking`}
          </p>
          {meta.warnings?.map((w) => (
            <p key={w} role="status" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">{w}</p>
          ))}
          {meta.analysis?.notes?.map((n) => <p key={n} className="text-xs text-slate-500">{n}</p>)}
          {result.hits.length === 0 ? (
            <p className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
              {result.mode !== "browse"
                ? "No evidence matched. Upload and process a document (indexing runs after clinical extraction), loosen the filters, or check the Dashboard's index status."
                : "No evidence matches these filters."}
            </p>
          ) : (
            <ul className="space-y-2">
              {result.hits.map((hit) => (
                <Result key={hit.evidence.evidence_id} hit={hit} open={openId === hit.evidence.evidence_id}
                  onToggle={() => setOpenId(openId === hit.evidence.evidence_id ? null : hit.evidence.evidence_id)} />
              ))}
            </ul>
          )}
          {result.mode !== "browse" && <p className="text-xs text-slate-400">{meta.note}</p>}
        </section>
      )}
    </div>
  );
}
