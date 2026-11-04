// Labels and styles shared by the processing UI.

export const IN_PROGRESS = ["queued", "processing"];

export const STATUS_LABELS = {
  not_processed: "Not processed",
  queued: "Queued",
  processing: "Processing",
  completed: "Completed",
  completed_with_errors: "Completed with errors",
  failed: "Failed",
};

export const STATUS_STYLES = {
  not_processed: "bg-slate-100 text-slate-700",
  queued: "bg-sky-100 text-sky-800",
  processing: "bg-sky-100 text-sky-800 animate-pulse",
  completed: "bg-emerald-100 text-emerald-800",
  completed_with_errors: "bg-amber-100 text-amber-900",
  failed: "bg-rose-100 text-rose-800",
};

export const METHOD_LABELS = {
  pymupdf: "PDF text layer (PyMuPDF)",
  pdfplumber: "PDF text layer (pdfplumber)",
  ocr_tesseract: "OCR (Tesseract)",
  none: "No text extracted",
};

export const PAGE_STATUS_LABELS = {
  completed: "Completed",
  needs_ocr: "Needs OCR",
  failed: "Failed",
};

export const PAGE_DOT = {
  completed: "bg-emerald-500",
  needs_ocr: "bg-amber-500",
  failed: "bg-rose-500",
};

// Phase 4
export const IMAGE_STATUS_LABELS = { extracted: "Extracted", failed: "Not extracted" };

export const IMAGE_OCR_LABELS = {
  not_requested: "Image OCR not requested",
  completed: "Text found in image (OCR)",
  no_text: "No text found in image",
  skipped_page_scan: "Full-page scan (text handled by page OCR)",
  unavailable: "OCR unavailable",
  failed: "OCR failed",
};

export const TABLE_METHOD_LABELS = { pymupdf_find_tables: "PyMuPDF table detection (heuristic)" };

export function inProgress(doc) {
  return IN_PROGRESS.includes(doc.processing_status) || IN_PROGRESS.includes(doc.multimodal_status);
}
