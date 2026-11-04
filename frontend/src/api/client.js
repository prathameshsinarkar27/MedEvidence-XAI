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

async function request(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, { signal });
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
