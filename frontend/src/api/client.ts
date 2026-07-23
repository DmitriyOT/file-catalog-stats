export interface JobStatus {
  id: number;
  status: "running" | "done" | "failed";
  started_at: string;
  started_at_nsk: string;
  finished_at: string | null;
  names_received: number;
  files_downloaded: number;
  error: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error(body?.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export function startJob(): Promise<JobStatus> {
  return request<JobStatus>("/api/job/start", { method: "POST" });
}

export function getJobStatus(): Promise<JobStatus | null> {
  return request<JobStatus | null>("/api/job/status");
}
