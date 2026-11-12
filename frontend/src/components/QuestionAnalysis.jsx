import { useEffect, useState } from "react";
import { getReasoningConfig, verifyQuestion } from "../api/client.js";
import { ASSERTION_LABELS, ENTITY_LABELS } from "../utils/processing.js";

const EXAMPLES = [
  "What was the latest HbA1c?",
  "Compare HbA1c in May 2026 and August 2026",
  "What is the blood pressure on 12-Aug-2026?",
  "Does the patient have chest pain?",
  "Is metformin prescribed for diabetes?",
  "List all medications",
];

const STATE_STYLE = {
  supported: ["Supported", "border-emerald-300 bg-emerald-50 text-emerald-900"],
  partially_supported: ["Partially supported", "border-amber-300 bg-amber-50 text-amber-900"],
  conflicting: ["Conflicting evidence", "border-rose-300 bg-rose-50 text-rose-900"],
  insufficient_evidence: ["Insufficient evidence", "border-slate-300 bg-slate-100 text-slate-800"],
};
const STATE_MEANING = {
  supported: "Direct, in-scope evidence exists for every part of the question and nothing in scope contradicts it.",
  partially_supported: "Some evidence exists, but it is indirect, outside what the question restricts, hedged, low-scored or incomplete.",
  conflicting: "In-scope evidence contains a possible contradiction. Read the conflict analysis below.",
  insufficient_evidence: "No relevant evidence was found (or the question asks for advice, which documents cannot support).",
};
const CATEGORY_STYLE = {
  temporal_change: ["Temporal change", "bg-sky-100 text-sky-800"],
  measurement_variation: ["Measurement variation", "bg-slate-200 text-slate-800"],
  possible_contradiction: ["Possible contradiction", "bg-rose-100 text-rose-800"],
};
const ROLE_STYLE = {
  supporting: ["Supporting", "bg-emerald-100 text-emerald-800"],
  context: ["Context", "bg-amber-100 text-amber-800"],
  excluded: ["Excluded", "bg-slate-100 text-slate-500"],
};
const TERM_LABELS = {
  relevance: "Semantic relevance", entity: "Entity agreement", value: "Value consistency", temporal: "Temporal consistency",
  confidence: "Extraction confidence", source: "Source reliability", directness: "Directness", agreement: "Agreement among units",
};
const KIND_STYLE = { decisive: "text-slate-900 font-medium", limiting: "text-amber-900", info: "text-slate-600" };

function valueText(e) {
  if (e.entity_type === "date") return e.date_iso ?? e.date_text ?? "—";
  if (e.value_text == null) return "—";
  const unit = e.unit_text && !e.value_text.includes(e.unit_text) ? ` ${e.unit_text}` : "";
  return `${e.value_comparator ?? ""}${e.value_text}${unit}`;
}

function Badge({ style, children }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs ${style}`}>{children}</span>;
}

function Understanding({ u }) {
  const rows = [
    ["Question type", `${u.primary}${u.types.length > 1 ? ` (also: ${u.types.filter((t) => t !== u.primary).join(", ")})` : ""}`],
    ["Entities", u.entities.length ? u.entities.map((n) => `${n} [${ENTITY_LABELS[u.entity_types[n]] ?? u.entity_types[n]}]`).join(", ") : "none recognised"],
    ["Dates / periods", u.periods.length ? u.periods.map(([a, b]) => (a === b ? a : `${a} to ${b}`)).join("; ") : u.recency ?? "none"],
    ["Stated values", u.value_constraints.length ? u.value_constraints.map((c) => c.text).join("; ") : "none"],
    ["Requested", [...u.requested, ...u.requested_entity_types].join(", ") || "—"],
  ];
  if (u.page_hint) rows.push(["Page", String(u.page_hint)]);
  if (u.assertion_focus) rows.push(["Statement kind", u.assertion_focus]);
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-700">1. Question understanding</h3>
      <dl className="mt-2 grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="text-slate-800">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-slate-500">
        Triggered by: {Object.entries(u.cues).map(([t, c]) => `${t} (${c.slice(0, 3).join(", ")})`).join("; ") || "no cue words"}
      </p>
      {u.notes.map((n) => (
        <p key={n} className="mt-1 text-xs text-amber-800">{n}</p>
      ))}
    </section>
  );
}

function StateCard({ s, counts }) {
  const [label, style] = STATE_STYLE[s.state];
  return (
    <section className={`rounded-lg border p-4 ${style}`} aria-live="polite">
      <p className="text-xs uppercase tracking-wide opacity-70">Evidence state</p>
      <p className="text-xl font-semibold">{label}</p>
      <p className="mt-1 text-sm">{STATE_MEANING[s.state]}</p>
      <ul className="mt-3 space-y-1 text-sm">
        {s.reasons.map((r, i) => (
          <li key={`${r.code}-${i}`} className={KIND_STYLE[r.kind]}>{r.text}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs opacity-80">
        {s.supporting_evidence_ids.length} supporting · {s.context_evidence_ids.length} context · {counts.possible_contradiction} possible
        contradiction(s) · {counts.temporal_change} temporal change(s)
        {s.claim_assessment ? ` · the value stated in the question is ${s.claim_assessment} by the evidence` : ""}
      </p>
      <p className="mt-2 text-xs opacity-80">This describes the evidence, not the truth of any answer. Answers are generated in the "Ask a Question" tab.</p>
    </section>
  );
}

function Terms({ v }) {
  return (
    <div className="text-xs">
      <p className="uppercase tracking-wide text-slate-500">Evidence score = Σ(weight × score) ÷ Σ(weights that apply)</p>
      <table className="mt-1 w-full border-collapse">
        <tbody>
          {Object.entries(v.terms).map(([name, t]) => (
            <tr key={name} className={t.score == null ? "text-slate-400" : "text-slate-800"} title={t.note}>
              <td className="py-0.5 pr-2">{TERM_LABELS[name]}</td>
              <td className="w-24 pr-2">
                <span className="block h-1.5 overflow-hidden rounded bg-slate-100">
                  <span className="block h-full bg-emerald-500" style={{ width: `${(t.score ?? 0) * 100}%` }} />
                </span>
              </td>
              <td className="whitespace-nowrap pr-2 font-mono">{t.score == null ? "n/a" : `${t.score.toFixed(2)} × ${t.weight}`}</td>
              <td className="pr-2 text-slate-500">{t.note}</td>
              <td className="text-right font-mono">{t.contribution == null ? "" : t.contribution.toFixed(3)}</td>
            </tr>
          ))}
          <tr className="border-t border-slate-200 font-medium text-slate-800">
            <td colSpan={4} className="pt-1">Evidence score (orders and gates evidence; not a probability)</td>
            <td className="pt-1 text-right font-mono">{v.score.toFixed(3)}</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-1 text-slate-600">
        Constraints: {Object.entries(v.constraints).filter(([, s]) => s !== "n/a").map(([k, s]) => `${k} ${s}`).join(", ") || "none"}
        {v.directness_reasons.length > 0 && ` · why ${v.directness}: ${v.directness_reasons.join(", ")}`}
        {v.claim_check ? ` · stated value ${v.claim_check}` : ""}
      </p>
    </div>
  );
}

function EvidenceRow({ hit }) {
  const [open, setOpen] = useState(false);
  const e = hit.evidence;
  const v = hit.verification;
  const [roleLabel, roleStyle] = ROLE_STYLE[v.role];
  return (
    <li className={`rounded-md border border-slate-200 bg-white ${v.role === "excluded" ? "opacity-60" : ""}`}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-slate-50">
        <span className="w-16 shrink-0 text-xs text-slate-500" title="Evidence score. Not a probability.">
          <span className="block font-mono text-slate-800">{v.score.toFixed(3)}</span>
          <span className="block">retrieval #{hit.retrieval_rank}</span>
        </span>
        <span className="min-w-0 flex-1 text-sm">
          <span className="font-medium text-slate-900">{e.entity_name}</span>{" "}
          <span className="font-mono text-slate-700">{valueText(e)}</span>
          <span className="ml-2 text-xs text-slate-500">
            {ENTITY_LABELS[e.entity_type]}
            {e.assertion !== "affirmed" ? ` · ${ASSERTION_LABELS[e.assertion] ?? e.assertion}` : ""}
            {e.date_iso ? ` · ${e.date_iso}` : ""}
          </span>
          <span className="block truncate text-xs text-slate-500">{e.document_filename} · page {e.page_number} · {e.source_text}</span>
        </span>
        <Badge style={roleStyle}>{roleLabel}</Badge>
        <Badge style="bg-slate-100 text-slate-700">{v.directness.replace("_", " ")}</Badge>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3">
          <p className="text-sm text-slate-800">&ldquo;{e.source_text}&rdquo;</p>
          <p className="text-xs text-slate-500">
            {e.document_filename} → page {e.page_number} → {e.source_field.replace("_", " ")} · extraction {e.extraction_method}
          </p>
          {v.assertion_note && <p className="text-xs text-amber-800">This evidence {v.assertion_note}.</p>}
          <Terms v={v} />
          {(v.corroborating_ids.length > 0 || v.conflict_ids.length > 0) && (
            <p className="text-xs text-slate-600">
              {v.corroborating_ids.length} other item(s) state the same finding; {v.conflict_ids.length} possible contradiction(s) involve it.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function Conflicts({ analysis, byId }) {
  const label = (id) => {
    const e = byId[id];
    return e ? `${valueText(e)}${e.date_iso ? ` (${e.date_iso})` : ""} · ${e.document_filename} p.${e.page_number}` : id;
  };
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-700">3. Conflict analysis</h3>
      <p className="mt-1 text-xs text-slate-500">
        A different value is not automatically a contradiction: values on different dates are temporal changes; small same-day
        differences are measurement variation. Tolerances are uncalibrated defaults. Units are never converted.
      </p>
      {analysis.pairs.length === 0 && <p className="mt-2 text-sm text-slate-600">No differing findings about the same entity.</p>}
      <ul className="mt-2 space-y-2">
        {analysis.pairs.map((p, i) => {
          const [name, style] = CATEGORY_STYLE[p.category];
          return (
            <li key={i} className="rounded-md border border-slate-200 p-2 text-sm">
              <Badge style={style}>{name}</Badge>{" "}
              {p.strength === "weak" && <Badge style="bg-amber-100 text-amber-800">weak: time unknown</Badge>}{" "}
              {!p.in_scope && <Badge style="bg-slate-100 text-slate-500">outside the question's scope</Badge>}
              <p className="mt-1 text-slate-800"><span className="font-medium">{p.entity_name}:</span> {p.explanation}</p>
              <p className="text-xs text-slate-500">{p.evidence_ids.map(label).join("  ↔  ")}</p>
            </li>
          );
        })}
      </ul>
      {Object.entries(analysis.timelines).map(([name, points]) => (
        <div key={name} className="mt-3 text-sm">
          <p className="text-xs uppercase tracking-wide text-slate-500">Timeline: {name}</p>
          <p className="font-mono text-slate-800">{points.map((p) => `${p.date}: ${p.value}${p.unit ? ` ${p.unit}` : ""}`).join("  →  ")}</p>
        </div>
      ))}
      {analysis.skipped.length > 0 && (
        <details className="mt-3 text-xs text-slate-600">
          <summary className="cursor-pointer">{analysis.skipped.length} pair(s) not compared</summary>
          <ul className="mt-1 list-disc pl-5">{analysis.skipped.map((s, i) => <li key={i}>{s.entity_name}: {s.text}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

export default function QuestionAnalysis() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState(null);

  useEffect(() => {
    getReasoningConfig().then(setConfig).catch(() => {});
  }, []);

  async function run(text) {
    const q = (text ?? question).trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await verifyQuestion({ q }));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const byId = result ? Object.fromEntries(result.ranked_evidence.map((h) => [h.evidence.evidence_id, h.evidence])) : {};

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Question analysis and evidence verification</h2>
        <p className="mt-1 text-xs text-slate-500">
          Ask a question about the uploaded documents. This phase shows how the question is understood, which evidence is retrieved and
          verified, whether the evidence conflicts, and the resulting evidence state. It does not write an answer (Phase 9) and gives no
          medical advice.
        </p>
        <form onSubmit={(e) => { e.preventDefault(); run(); }} className="mt-3 flex gap-2">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} placeholder="e.g. What was the latest HbA1c?"
            aria-label="Question" className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm" />
          <button type="submit" disabled={busy || !question.trim()} className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {busy ? "Analysing…" : "Analyse"}
          </button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => { setQuestion(ex); run(ex); }} className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50">
              {ex}
            </button>
          ))}
        </div>
        {config && (
          <details className="mt-3 text-xs text-slate-600">
            <summary className="cursor-pointer">Verification formula, weights and thresholds</summary>
            <p className="mt-1 font-mono">{config.verification_formula}</p>
            <p className="mt-1">Weights: {Object.entries(config.weights).map(([k, v]) => `${k} ${v}`).join(", ")}</p>
            <p>Thresholds: {Object.entries(config.thresholds).map(([k, v]) => `${k} ${v}`).join(", ")}</p>
            <p>Same-time tolerance (relative): {Object.entries(config.conflict_tolerances).map(([k, v]) => `${k} ${v}`).join(", ")}</p>
            <p className="mt-1 text-amber-800">{config.note}</p>
          </details>
        )}
      </section>

      {error && <p role="alert" className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}

      {result && (
        <>
          <StateCard s={result.evidence_state} counts={result.conflict_analysis.counts} />
          <Understanding u={result.understanding} />
          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-700">2. Ranked evidence and verification</h3>
            <p className="mt-1 text-xs text-slate-500">
              {result.retrieval.returned} item(s) retrieved with hybrid ranking ({result.retrieval.is_semantic ? "semantic" : "lexical"} embedding
              {result.retrieval.embedding_model ? `: ${result.retrieval.embedding_model}` : ""}). Click an item to see its verification score.
            </p>
            {result.retrieval.warnings.map((w) => <p key={w} className="mt-1 text-xs text-amber-800">{w}</p>)}
            {result.ranked_evidence.length === 0 ? (
              <p className="mt-2 text-sm text-slate-600">No evidence was retrieved. Upload and process documents first.</p>
            ) : (
              <>
                <ul className="mt-2 space-y-2">
                  {result.ranked_evidence.filter((h) => h.verification.role !== "excluded").map((h) => <EvidenceRow key={h.evidence.evidence_id} hit={h} />)}
                </ul>
                {result.ranked_evidence.some((h) => h.verification.role === "excluded") && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-slate-600">
                      {result.ranked_evidence.filter((h) => h.verification.role === "excluded").length} retrieved item(s) excluded (wrong entity or below the minimum score)
                    </summary>
                    <ul className="mt-2 space-y-2">
                      {result.ranked_evidence.filter((h) => h.verification.role === "excluded").map((h) => <EvidenceRow key={h.evidence.evidence_id} hit={h} />)}
                    </ul>
                  </details>
                )}
              </>
            )}
          </section>
          <Conflicts analysis={result.conflict_analysis} byId={byId} />
          <p className="text-xs text-slate-500">{result.note}</p>
        </>
      )}
    </div>
  );
}
