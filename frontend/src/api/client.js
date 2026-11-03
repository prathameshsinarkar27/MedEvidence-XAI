// Thin API client. All requests go through the Vite dev proxy (/api -> backend).

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, { signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Cannot reach the backend API.", 0);
  }
  if (!response.ok && response.status !== 503) {
    throw new ApiError(`Backend returned HTTP ${response.status}.`, response.status);
  }
  return response.json();
}

export const getHealth = (opts) => request("/health", opts);
