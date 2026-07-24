import { useState } from "react";
import { cancelJob, JobStatus, startJob } from "../api/client";
import { useJobStatus } from "../components/JobStatusProvider";

const STATUS_LABELS: Record<JobStatus["status"], string> = {
  running: "Выполняется",
  done: "Завершено",
  failed: "Ошибка",
  cancelled: "Отменено пользователем",
};

export default function DownloadPage() {
  const { job, refresh, unreachable } = useJobStatus();
  const [error, setError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

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

  const handleCancel = async () => {
    setCancelError(null);
    setCancelling(true);
    try {
      await cancelJob();
      await refresh();
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  };

  const running = job?.status === "running";
  const banned = running && job?.banned_until_nsk != null;

  return (
    <section>
      <h2>Скачивание данных</h2>

      {unreachable && (
        <p className="error">Нет связи с backend: статус задачи может быть устаревшим.</p>
      )}

      <button onClick={handleStart} disabled={running}>
        {running ? "Скачивание..." : "Скачать данные"}
      </button>
      {running && (
        <button className="danger" onClick={handleCancel} disabled={cancelling}>
          {cancelling ? "Отменяю..." : "Отменить"}
        </button>
      )}

      {error && <p className="error">{error}</p>}
      {cancelError && <p className="error">Не удалось отменить задачу: {cancelError}</p>}

      {banned && (
        <div className="warning">
          Внешнее API временно ограничило запросы: ждём разблокировки до{" "}
          <b>{job.banned_until_nsk}</b> (НСК). Скачивание продолжится автоматически, интервал
          между запросами увеличен.
        </div>
      )}

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
