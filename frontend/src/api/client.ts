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
    const detail = body?.detail;
    // FastAPI при 422 отдаёт detail массивом объектов с полем msg
    const message = Array.isArray(detail)
      ? detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
      : (detail ?? `HTTP ${resp.status}`);
    throw new Error(message);
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

export function getFiles(
  page: number,
  perPage: number,
  sort: "asc" | "desc",
  search = "",
): Promise<FilePage> {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
    sort,
  });
  if (search) params.set("search", search);
  return request<FilePage>(`/api/files?${params}`);
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
