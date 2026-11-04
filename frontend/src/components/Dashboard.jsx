import { useCallback, useEffect, useState } from "react";
import { getCapabilities, getHealth } from "../api/client.js";
import StatusCard from "./StatusCard.jsx";
import PhaseRoadmap from "./PhaseRoadmap.jsx";

const DB_TONE = { connected: "ok", unreachable: "bad", not_configured: "warn" };

export default function Dashboard() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (signal) => {
    setLoading(true);
    try {
      setHealth(await getHealth({ signal }));
      setError(null);
      setCapabilities(await getCapabilities({ signal }).catch(() => null));
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
    <div className="space-y-6">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => refresh()}
          disabled={loading}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
        >
          {loading ? "Checking…" : "Refresh"}
        </button>
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
              <p className="text-xs text-slate-400">Checked {new Date(health.timestamp).toLocaleTimeString()}</p>
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

      <StatusCard
        title="PDF extraction & OCR"
        badge={!capabilities ? "Unknown" : capabilities.ocr.available ? "OCR ready" : "OCR not set up"}
        tone={!capabilities ? "idle" : capabilities.ocr.available ? "ok" : "bad"}
      >
        {!capabilities && <p>Status unavailable until the backend responds.</p>}
        {capabilities && (
          <>
            <p>
              Text layer: {capabilities.pdf_engine} &middot; OCR:{" "}
              {capabilities.ocr.available ? `Tesseract ${capabilities.ocr.version}` : "Tesseract unavailable"}
              {" "}({capabilities.ocr.requested_languages.join(", ")})
            </p>
            {capabilities.ocr.message && (
              <p role="alert" className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-rose-900">
                {capabilities.ocr.message}
              </p>
            )}
            <p className="text-xs text-slate-400">
              Pages with fewer than {capabilities.min_text_chars_per_page} characters are sent to OCR &middot; OCR
              at {capabilities.ocr_dpi} dpi &middot; max {capabilities.max_pdf_pages} pages per PDF. Text-only PDFs
              work without Tesseract.
            </p>
          </>
        )}
      </StatusCard>

      <PhaseRoadmap />

      <p className="text-xs text-slate-400">
        Evidence, question-answering and evaluation metrics are shown here once those components exist. Not yet
        evaluated.
      </p>
    </div>
  );
}
