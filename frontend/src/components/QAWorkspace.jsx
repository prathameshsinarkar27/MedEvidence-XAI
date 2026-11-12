import { useEffect, useState } from "react";
import { askQuestion, getQAConfig } from "../api/client.js";
import { ASSERTION_LABELS, ENTITY_LABELS } from "../utils/processing.js";
import SourcePreview from "./SourcePreview.jsx";

const EXAMPLES = [
  "What was the latest HbA1c?",
  "How did HbA1c change over time?",
  "What was the blood pressure on 12-Aug-2026?",
  "Does the patient have chest pain?",
  "List all medications",
  "What was the serum ferritin?",
];

const STATUS = {
  answered: ["Answered from the documents", "border-emerald-300 bg-emerald-50 text-emerald-950"],
  answered_with_caveats: ["Answered with caveats", "border-amber-300 bg-amber-50 text-amber-950"],
  conflict_reported: ["Conflicting evidence reported", "border-rose-300 bg-rose-50 text-rose-950"],
  abstained: ["Not answered: insufficient evidence", "border-slate-300 bg-slate-100 text-slate-900"],
};
const SUPPORT_LABEL = { full: "Full", partial: "Partial", conflicting: "Conflicting", none: "None" };

function valueText(e) {
  if (e.entity_type === "date") return e.date_iso ?? e.date_text ?? "—";
  if (e.value_text == null) return "—";
  const unit = e.unit_text && !e.value_text.includes(e.unit_text) ? ` ${e.unit_text}` : "";
  return `${e.value_comparator ?? ""}${e.value_text}${unit}`;
}

// "Answer [1] [2]" -> text with markers that jump to the claim table row.
function AnswerText({ text }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="mt-2 text-base leading-relaxed">
      {parts.map((part, i) => {
        const m = /^\[(\d+)\]$/.exec(part);
        return m ? (
          <a key={i} href={`#claim-${m[1]}`} className="mx-0.5 align-super text-xs font-semibold text-sky-800 underline">
            [{m[1]}]
          </a>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </p>
  );
}

function Confidence({ c }) {
  const ev = c.evidence_confidence;
  const sup = c.answer_support;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-label="Confidence">
      <h3 className="text-sm font-semibold text-slate-700">Confidence (three separate things)</h3>
      <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Model confidence</dt>
          <dd className="font-medium text-slate-800">Not available</dd>
          <dd className="text-xs text-slate-500">{c.model_confidence.note}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Evidence confidence</dt>
          <dd className="font-mono font-medium text-slate-800">{ev.score == null ? "—" : ev.score.toFixed(2)}</dd>
          <dd className="text-xs text-slate-500">
            {ev.score == null ? "No evidence is cited." : `Weakest cited item (${ev.cited_items} cited); extraction confidence ${ev.min_extraction_confidence}–${ev.mean_extraction_confidence}.`}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Answer support</dt>
          <dd className="font-medium text-slate-800">{SUPPORT_LABEL[sup.label]}</dd>
          <dd className="text-xs text-slate-500">
            {sup.claims_with_evidence}/{sup.claims} claims cite evidence · {sup.supporting_items} supporting item(s)
            {sup.conflicting_items ? ` · ${sup.conflicting_items} conflicting` : ""}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-slate-500">{c.note} These are heuristic indicators, not medical certainty.</p>
    </section>
  );
}

function Claims({ claims }) {
  if (claims.length === 0) return null;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-700">Claim → evidence → source</h3>
      <table className="mt-2 w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr><th className="pr-2">#</th><th className="pr-2">Claim</th><th>Evidence and source</th></tr>
        </thead>
        <tbody>
          {claims.map((c) => (
            <tr key={c.id} id={`claim-${c.marker}`} className="border-t border-slate-100 align-top">
              <td className="py-2 pr-2 font-mono text-xs">[{c.marker}]</td>
              <td className="py-2 pr-3">{c.text}</td>
              <td className="py-2 text-xs text-slate-600">
                {c.sources.map((s) => (
                  <p key={s.evidence_id}>
                    {s.document_filename} · page {s.page_number} · &ldquo;{s.source_text}&rdquo;
                  </p>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// The source sentence with the extracted mention highlighted.
function Highlighted({ text, mention }) {
  const at = mention ? text.toLowerCase().indexOf(mention.toLowerCase()) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded bg-yellow-200 px-0.5">{text.slice(at, at + mention.length)}</mark>
      {text.slice(at + mention.length)}
    </>
  );
}

function EvidenceCard({ card }) {
  const [open, setOpen] = useState(false);
  const e = card.evidence;
  const boxes = e.region ? [{ id: e.evidence_id, region: e.region, label: `${e.entity_name} ${valueText(e)}`, active: true }] : [];
  return (
    <li className="rounded-md border border-slate-200 bg-white">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-slate-50">
        <span className="min-w-0 flex-1 text-sm">
          <span className="font-medium text-slate-900">{e.entity_name}</span>{" "}
          <span className="font-mono text-slate-700">{valueText(e)}</span>
          <span className="ml-2 text-xs text-slate-500">
            {ENTITY_LABELS[e.entity_type]}
            {e.assertion !== "affirmed" ? ` · ${ASSERTION_LABELS[e.assertion] ?? e.assertion}` : ""}
            {e.date_iso ? ` · ${e.date_iso}` : ""}
          </span>
          <span className="block truncate text-xs text-slate-500">{e.document_filename} · page {e.page_number}</span>
        </span>
        {card.cited_by_claims.length > 0 && (
          <span className="rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800">cited by {card.cited_by_claims.map((n) => `[${n}]`).join(" ")}</span>
        )}
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Relevant text</p>
            <p className="text-sm text-slate-800"><Highlighted text={e.source_text} mention={e.mention_text} /></p>
            <p className="mt-1 text-xs text-slate-500">
              {e.document_filename} → page {e.page_number} → {e.modality === "table" ? "table row" : e.modality.includes("ocr") ? "OCR text" : "text layer"} · verification score{" "}
              {card.verification_score.toFixed(2)} (not a probability)
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Why this evidence was selected</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
              {card.why_selected.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
          <SourcePreview documentId={e.document_id} pageNumber={e.page_number} boxes={boxes} />
        </div>
      )}
    </li>
  );
}

function EvidenceGroup({ title, hint, cards, defaultOpen }) {
  if (cards.length === 0) return null;
  return (
    <details open={defaultOpen} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <summary className="cursor-pointer text-sm font-semibold text-slate-700">
        {title} ({cards.length})
      </summary>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
      <ul className="mt-2 space-y-2">{cards.map((c) => <EvidenceCard key={c.evidence.evidence_id} card={c} />)}</ul>
    </details>
  );
}

export default function QAWorkspace() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState(null);

  useEffect(() => {
    getQAConfig().then(setConfig).catch(() => {});
  }, []);

  async function run(text) {
    const q = (text ?? question).trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await askQuestion({ q }));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const [label, style] = result ? STATUS[result.status] : [];
  const u = result?.understanding;

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Ask a question about the uploaded documents</h2>
        <p className="mt-1 text-xs text-slate-500">
          Answers restate what the documents state and cite their sources. The system gives no diagnosis and no treatment
          recommendation, and says so when the documents do not contain enough evidence.
          {config && ` Answer provider: ${config.provider === "extractive" ? "deterministic extractive (no model)" : `${config.llm_model ?? "LLM"} (${config.llm_local ? "local" : "external"} endpoint, output validated)`}.`}
        </p>
        <form onSubmit={(e) => { e.preventDefault(); run(); }} className="mt-3 flex gap-2">
          <label className="sr-only" htmlFor="qa-question">Question</label>
          <input id="qa-question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
            placeholder="e.g. What was the latest HbA1c?" className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm" />
          <button type="submit" disabled={busy || !question.trim()} className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
            {busy ? "Working…" : "Ask"}
          </button>
        </form>
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => { setQuestion(ex); run(ex); }} className="rounded-full border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50">
              {ex}
            </button>
          ))}
        </div>
      </section>

      {error && <p role="alert" className="rounded-md border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-900">{error}</p>}

      {result && (
        <>
          <section className={`rounded-lg border p-5 ${style}`} aria-live="polite">
            <p className="text-xs uppercase tracking-wide opacity-70">Question</p>
            <p className="font-medium">{result.question}</p>
            <p className="mt-3 text-xs uppercase tracking-wide opacity-70">{label}</p>
            <AnswerText text={result.answer} />
            {result.context_notes.length > 0 && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                {result.context_notes.map((n, i) => <li key={i}>Related, not answering the question: {n}</li>)}
              </ul>
            )}
            {result.caveats.length > 0 && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                {result.caveats.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            )}
            {result.warnings.length > 0 && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs opacity-80">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
            <p className="mt-3 text-xs opacity-80">
              Written by: {result.provider.used === "extractive" ? "deterministic extractive composer" : result.provider.used}
              {result.provider.external_call_made ? " · evidence text was sent to an external service" : ""}
              {result.provider.fallback ? " · the configured LLM was not used for this answer" : ""}
            </p>
          </section>

          <Confidence c={result.confidence} />
          <Claims claims={result.claims} />

          <EvidenceGroup title="Supporting evidence" cards={result.supporting_evidence} defaultOpen
            hint="Direct, in-scope evidence the answer is built from. Open an item to see the source text, the reason it was selected and the page." />
          <EvidenceGroup title="Conflicting evidence" cards={result.conflicting_evidence} defaultOpen
            hint="Items that state different values about the same finding. The system does not decide which is correct." />
          <EvidenceGroup title="Related context (not used as support)" cards={result.context_evidence} defaultOpen={false}
            hint="Retrieved and verified as related, but indirect, out of scope or hedged, so not used to support the answer." />

          <details className="rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-sm">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">How the question was understood</summary>
            <p className="mt-2 text-slate-700">
              Type: {u.primary}; entities: {u.entities.join(", ") || "none recognised"}; evidence state: {result.evidence_state.state}.
            </p>
            <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
              {result.evidence_state.reasons.map((r, i) => <li key={i}>{r.text}</li>)}
            </ul>
          </details>

          <p role="note" className="text-xs text-slate-500">{result.disclaimer}</p>
        </>
      )}
    </div>
  );
}
