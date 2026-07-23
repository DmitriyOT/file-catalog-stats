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

export interface FileItem {
  id: number;
  name: string;
  downloaded_at: string;
  downloaded_at_nsk: string;
}

export interface FilePage {
  items: FileItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export function getFiles(page: number, perPage: number, sort: "asc" | "desc"): Promise<FilePage> {
  return request<FilePage>(`/api/files?page=${page}&per_page=${perPage}&sort=${sort}`);
}

export interface FileStats {
  id: number;
  name: string;
  counts: Record<string, number>;
}

export interface StatsResponse {
  total: Record<string, number>;
  files: FileStats[];
}

export function getStats(fileIds: number[], all: boolean): Promise<StatsResponse> {
  return request<StatsResponse>("/api/stats", {
    method: "POST",
    body: JSON.stringify({ file_ids: fileIds, all }),
  });
}
