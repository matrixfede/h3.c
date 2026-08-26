import type {
  Asset,
  Capabilities,
  Job,
  JobSpec,
  SystemInfo,
  ValidationReport,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(response.status, detail?.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "request failed");
  }

  /** Validation failures arrive as { errors: [...] }. */
  get errors(): string[] {
    const detail = this.detail as { errors?: string[] } | string;
    if (typeof detail === "object" && Array.isArray(detail?.errors)) {
      return detail.errors;
    }
    return [String(this.message)];
  }
}

export const api = {
  system: () => request<SystemInfo>("/api/system"),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: number) => request<Job>(`/api/jobs/${id}`),
  validate: (spec: JobSpec) =>
    request<ValidationReport>("/api/jobs/validate", {
      method: "POST",
      body: JSON.stringify(spec),
    }),
  submit: (spec: JobSpec) =>
    request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(spec) }),
  cancel: (id: number) =>
    request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  assets: () => request<Asset[]>("/api/assets"),
  upload: async (file: File): Promise<Asset> => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/assets", { method: "POST", body });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new ApiError(response.status, detail?.detail ?? response.statusText);
    }
    return (await response.json()) as Asset;
  },
  videoUrl: (id: number) => `/api/jobs/${id}/video`,
  posterUrl: (id: number) => `/api/jobs/${id}/poster`,
  logUrl: (id: number) => `/api/jobs/${id}/log`,
  previewUrl: (id: number, step: number | null) =>
    `/api/jobs/${id}/preview?step=${step ?? 0}`,
  assetUrl: (id: number) => `/api/assets/${id}/file`,
};

/** Subscribe to one job's progress; returns an unsubscribe function. */
export function watchJob(id: number, onJob: (job: Job) => void): () => void {
  const source = new EventSource(`/api/jobs/${id}/events`);
  source.addEventListener("job", (event) => {
    onJob(JSON.parse((event as MessageEvent).data) as Job);
  });
  source.addEventListener("error", () => source.close());
  return () => source.close();
}
