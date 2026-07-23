import { useCallback, useEffect, useRef, useState } from "react";
import { getJobStatus, JobStatus, startJob } from "../api/client";

const POLL_INTERVAL_MS = 1500;

const STATUS_LABELS: Record<JobStatus["status"], string> = {
  running: "Выполняется",
  done: "Завершено",
  failed: "Ошибка",
};

export default function DownloadPage() {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await getJobStatus();
      setJob(status);
      if (status?.status !== "running") stopPolling();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      stopPolling();
    }
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    timer.current = setInterval(refresh, POLL_INTERVAL_MS);
  }, [refresh, stopPolling]);

  useEffect(() => {
    let cancelled = false;
    // если задача уже выполняется — продолжаем следить
    getJobStatus().then((s) => {
      if (cancelled) return;
      setJob(s);
      if (s?.status === "running") startPolling();
    });
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  const handleStart = async () => {
    setError(null);
    try {
      const status = await startJob();
      setJob(status);
      startPolling();
    } catch (e) {
      // 409 — задача уже запущена, просто следим за ней
      setError(e instanceof Error ? e.message : String(e));
      startPolling();
    }
  };

  const running = job?.status === "running";

  return (
    <section>
      <h2>Скачивание данных</h2>
      <button onClick={handleStart} disabled={running}>
        {running ? "Скачивание..." : "Скачать данные"}
      </button>

      {error && <p className="error">{error}</p>}

      {job && (
        <div className="card">
          <p>
            Статус: <b>{STATUS_LABELS[job.status]}</b>
          </p>
          <p>Время старта (НСК): {job.started_at_nsk}</p>
          <p>
            Получено {job.names_received} названий файлов,{" "}
            {running ? "скачиваю" : "скачано"} {job.files_downloaded} из{" "}
            {job.names_received}
          </p>
          {job.status === "failed" && <p className="error">{job.error}</p>}
        </div>
      )}
    </section>
  );
}
