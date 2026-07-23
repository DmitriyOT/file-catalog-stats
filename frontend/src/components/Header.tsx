import { NavLink } from "react-router-dom";
import { useJobStatus } from "./JobStatusProvider";

export default function Header() {
  const { job } = useJobStatus();
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
