import { useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import DocumentsPage from "./components/DocumentsPage.jsx";
import EvidenceExplorer from "./components/EvidenceExplorer.jsx";
import QuestionAnalysis from "./components/QuestionAnalysis.jsx";

const DISCLAIMER =
  "This is a research/educational prototype and is not a substitute for professional medical diagnosis or treatment.";

const TABS = [
  ["dashboard", "Dashboard"],
  ["documents", "Documents"],
  ["evidence", "Evidence Explorer"],
  ["question", "Question Analysis"],
];

export default function App() {
  const [tab, setTab] = useState("dashboard");

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 pt-4">
          <h1 className="text-lg font-semibold">MedEvidence-XAI</h1>
          <p className="text-xs text-slate-500">
            Evidence-grounded medical document understanding &mdash; Phase 8: question understanding and evidence verification
          </p>
          <nav className="mt-3 flex gap-1" aria-label="Main">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                aria-current={tab === id ? "page" : undefined}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                  tab === id
                    ? "border-slate-900 text-slate-900"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div role="note" className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {DISCLAIMER}
        </div>
        {tab === "dashboard" ? <Dashboard /> : tab === "documents" ? <DocumentsPage /> : tab === "evidence" ? <EvidenceExplorer /> : <QuestionAnalysis />}
      </main>
    </div>
  );
}
