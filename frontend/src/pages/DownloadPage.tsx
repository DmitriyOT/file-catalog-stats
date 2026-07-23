import { useState } from "react";
import { JobStatus, startJob } from "../api/client";
import { useJobStatus } from "../components/JobStatusProvider";

const STATUS_LABELS: Record<JobStatus["status"], string> = {
  running: "Выполняется",
  done: "Завершено",
  failed: "Ошибка",
};

export default function DownloadPage() {
  const { job, refresh } = useJobStatus();
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    setError(null);
    try {
      await startJob();
    } catch (e) {
      // 409 — задача уже запущена, просто следим за ней
      setError(e instanceof Error ? e.message : String(e));
    }
    // подхватываем актуальный статус и включаем polling, если задача выполняется
    await refresh();
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
