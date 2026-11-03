import { useCallback, useEffect, useState } from "react";
import { getHealth } from "./api/client.js";
import StatusCard from "./components/StatusCard.jsx";
import PhaseRoadmap from "./components/PhaseRoadmap.jsx";

const DISCLAIMER =
  "This is a research/educational prototype and is not a substitute for professional medical diagnosis or treatment.";

const DB_TONE = { connected: "ok", unreachable: "bad", not_configured: "warn" };

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (signal) => {
    setLoading(true);
    try {
      setHealth(await getHealth({ signal }));
      setError(null);
    } catch (err) {
      if (err.name === "AbortError") return;
      setHealth(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const db = health?.database;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold">MedEvidence-XAI</h1>
            <p className="text-xs text-slate-500">
              Evidence-grounded medical document understanding &mdash; Phase 1 foundation
            </p>
          </div>
          <button
            type="button"
            onClick={() => refresh()}
            disabled={loading}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            {loading ? "Checking…" : "Refresh"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div role="note" className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {DISCLAIMER}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <StatusCard
            title="Backend API"
            badge={error ? "Unreachable" : health ? (health.status === "ok" ? "Healthy" : "Degraded") : "Checking"}
            tone={error ? "bad" : health ? (health.status === "ok" ? "ok" : "warn") : "idle"}
          >
            {error && <p>{error} Is the backend running on port 8000?</p>}
            {health && (
              <>
                <p>
                  {health.app_name} v{health.version} ({health.environment})
                </p>
                <p className="text-xs text-slate-400">
                  Checked {new Date(health.timestamp).toLocaleTimeString()}
                </p>
              </>
            )}
          </StatusCard>

          <StatusCard
            title="PostgreSQL"
            badge={db ? db.status.replace("_", " ") : error ? "Unknown" : "Checking"}
            tone={db ? DB_TONE[db.status] ?? "idle" : "idle"}
          >
            {db && (
              <>
                <p>{db.detail}</p>
                {db.target && <p className="font-mono text-xs">{db.target}</p>}
                {db.server_version && <p className="text-xs text-slate-400">Server {db.server_version}</p>}
              </>
            )}
            {!db && <p>Status unavailable until the backend responds.</p>}
          </StatusCard>
        </div>

        <PhaseRoadmap />

        <p className="text-xs text-slate-400">
          Document, evidence, question-answering and evaluation metrics are shown here once those components exist.
          Not yet evaluated.
        </p>
      </main>
    </div>
  );
}
