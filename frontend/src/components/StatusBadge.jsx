import { STATUS_LABELS, STATUS_STYLES } from "../utils/processing.js";

export default function StatusBadge({ status }) {
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700"
      }`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
