// Static description of the development plan. Only Phases 1-2 exist; nothing here implies
// that later phases are implemented or evaluated.
const PHASES = [
  ["1", "Foundation + project skeleton", "done"],
  ["2", "Medical document upload + storage", "done"],
  ["3", "PDF text extraction + OCR", "planned"],
  ["4", "Multimodal document processing", "planned"],
  ["5", "Clinical information extraction", "planned"],
  ["6", "Evidence storage, index + semantic retrieval", "planned"],
  ["7", "Hybrid retrieval + ranking", "planned"],
  ["8", "Question understanding + verification", "planned"],
  ["9", "Evidence-grounded QA + explainability", "planned"],
  ["10", "Evaluation, robustness + final platform", "planned"],
];

export default function PhaseRoadmap() {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">Development roadmap</h2>
      <ol className="mt-3 divide-y divide-slate-100 text-sm">
        {PHASES.map(([n, label, state]) => (
          <li key={n} className="flex items-center justify-between py-2">
            <span className="text-slate-700">
              <span className="mr-2 font-mono text-xs text-slate-400">P{n}</span>
              {label}
            </span>
            <span className={state === "done" ? "text-emerald-700" : "text-slate-400"}>
              {state === "done" ? "Implemented" : "Not yet implemented"}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
