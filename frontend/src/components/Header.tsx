import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { getJobStatus, JobStatus } from "../api/client";

const POLL_INTERVAL_MS = 3000;

export default function Header() {
  const [job, setJob] = useState<JobStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await getJobStatus();
        if (!cancelled) setJob(status);
      } catch {
        // индикатор — не критично, просто пропускаем цикл
      }
    };
    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const running = job?.status === "running";

  return (
    <header className="nav">
      <h1>Сервис анализа файлов</h1>
      <nav>
        <NavLink to="/">Скачивание</NavLink>
        <NavLink to="/files">Файлы и расчёты</NavLink>
      </nav>
      {running && (
        <span className="download-badge" title={`Старт (НСК): ${job.started_at_nsk}`}>
          <span className="pulse" />
          Идёт скачивание: {job.files_downloaded} из {job.names_received}
        </span>
      )}
    </header>
  );
}
