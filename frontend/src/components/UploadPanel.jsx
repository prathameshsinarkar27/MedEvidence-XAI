import { useRef, useState } from "react";
import { uploadDocument } from "../api/client.js";
import { formatBytes } from "../utils/format.js";

// Client-side checks are a convenience only; the server re-validates everything.
function checkFile(file, policy) {
  if (!file) return "Choose a PDF file first.";
  const allowed = policy?.allowed_extensions ?? [".pdf"];
  if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) return "Only PDF files (.pdf) are accepted.";
  if (file.size === 0) return "The selected file is empty.";
  if (policy && file.size > policy.max_upload_size_bytes)
    return `The file is ${formatBytes(file.size)}; the maximum is ${formatBytes(policy.max_upload_size_bytes)}.`;
  return null;
}

export default function UploadPanel({ policy, onUploaded }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [state, setState] = useState("idle"); // idle | uploading | success | error
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState(null);

  const busy = state === "uploading";

  function onChange(event) {
    const chosen = event.target.files?.[0] ?? null;
    setFile(chosen);
    setProgress(0);
    const problem = chosen ? checkFile(chosen, policy) : null;
    setState(problem ? "error" : "idle");
    setMessage(problem);
  }

  async function onSubmit(event) {
    event.preventDefault();
    const problem = checkFile(file, policy);
    if (problem) {
      setState("error");
      setMessage(problem);
      return;
    }
    setState("uploading");
    setProgress(0);
    setMessage(null);
    try {
      // Some systems report an empty MIME type for PDFs; the server also verifies the %PDF- signature.
      const toSend = file.type === "application/pdf" ? file : new File([file], file.name, { type: "application/pdf" });
      const created = await uploadDocument(toSend, setProgress);
      setState("success");
      setMessage(`Uploaded “${created.original_filename}” (${formatBytes(created.file_size_bytes)}).`);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      onUploaded?.(created);
    } catch (err) {
      setState("error");
      setMessage(err.message);
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">Upload a medical document</h2>
      <p className="mt-1 text-xs text-slate-500">
        PDF only, up to {policy ? formatBytes(policy.max_upload_size_bytes) : "…"}. Use synthetic or anonymised
        documents only &mdash; never real patient data.
      </p>

      <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={onChange}
          disabled={busy}
          aria-label="PDF file"
          className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200"
        />
        <button
          type="submit"
          disabled={busy || !file}
          className="shrink-0 rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>

      {busy && (
        <div className="mt-3" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full bg-slate-700 transition-all" style={{ width: `${progress}%` }} />
          </div>
          <p className="mt-1 text-xs text-slate-500">{progress}%</p>
        </div>
      )}

      {message && (
        <p
          role={state === "error" ? "alert" : "status"}
          className={`mt-3 text-sm ${state === "error" ? "text-rose-700" : "text-emerald-700"}`}
        >
          {message}
        </p>
      )}
    </section>
  );
}
