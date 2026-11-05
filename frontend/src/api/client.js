// Thin API client. All requests go through the Vite dev proxy (/api -> backend).

export class ApiError extends Error {
  constructor(message, status, code = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function errorFromBody(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return new ApiError(detail, status);
  if (detail?.message) return new ApiError(detail.message, status, detail.code ?? null);
  if (Array.isArray(detail)) return new ApiError("The request was not valid (e.g. no file was provided).", status);
  return new ApiError(`Backend returned HTTP ${status}.`, status);
}

async function request(path, { signal, method = "GET" } = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, { signal, method });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Cannot reach the backend API.", 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw errorFromBody(body, response.status);
  return body;
}

export const getHealth = (opts) => request("/health", opts);
export const getUploadPolicy = (opts) => request("/documents/upload-policy", opts);
export const listDocuments = ({ limit = 20, offset = 0 } = {}, opts) =>
  request(`/documents?limit=${limit}&offset=${offset}`, opts);
export const getDocument = (id, opts) => request(`/documents/${encodeURIComponent(id)}`, opts);

// Phase 3: text extraction + OCR
const docPath = (id) => `/documents/${encodeURIComponent(id)}`;
export const startProcessing = (id, opts) => request(`${docPath(id)}/process`, { ...opts, method: "POST" });
export const getProcessingStatus = (id, opts) => request(`${docPath(id)}/processing`, opts);
export const listPages = (id, opts) => request(`${docPath(id)}/pages`, opts);
export const getPage = (id, pageNumber, opts) => request(`${docPath(id)}/pages/${pageNumber}`, opts);
export const getCapabilities = (opts) => request("/processing/capabilities", opts);

// Phase 4: tables and embedded images
export const startMultimodal = (id, { imageOcr } = {}, opts) =>
  request(`${docPath(id)}/multimodal${imageOcr == null ? "" : `?image_ocr=${imageOcr}`}`, { ...opts, method: "POST" });
export const getMultimodalStatus = (id, opts) => request(`${docPath(id)}/multimodal`, opts);
export const listTables = (id, opts) => request(`${docPath(id)}/tables`, opts);
export const getTable = (id, tableId, opts) => request(`${docPath(id)}/tables/${encodeURIComponent(tableId)}`, opts);
export const listImages = (id, opts) => request(`${docPath(id)}/images`, opts);
export const getImage = (id, imageId, opts) => request(`${docPath(id)}/images/${encodeURIComponent(imageId)}`, opts);
// URLs used directly as <img src>
export const imageFileUrl = (id, imageId) => `/api${docPath(id)}/images/${encodeURIComponent(imageId)}/file`;
export const pagePreviewUrl = (id, pageNumber) => `/api${docPath(id)}/pages/${pageNumber}/preview`;

// Phase 5: clinical information extraction
export const startClinical = (id, opts) => request(`${docPath(id)}/clinical-extraction`, { ...opts, method: "POST" });
export const getClinicalStatus = (id, opts) => request(`${docPath(id)}/clinical-extraction`, opts);
export const listClinicalEvidence = (id, { limit = 1000, offset = 0 } = {}, opts) =>
  request(`${docPath(id)}/clinical-evidence?limit=${limit}&offset=${offset}`, opts);

// fetch() cannot report upload progress, so uploads use XMLHttpRequest.
export function uploadDocument(file, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new ApiError("Cannot reach the backend API.", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(errorFromBody(xhr.response, xhr.status));
    };
    xhr.send(form);
  });
}
