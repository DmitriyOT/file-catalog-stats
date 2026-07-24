import { NavLink } from "react-router-dom";
import { useJobStatus } from "./JobStatusProvider";
import { useTheme } from "../theme";

/** «24.07.2026 14:05:30» → «14:05»; если формат иной — возвращаем как есть */
function shortTime(nsk: string): string {
  return nsk.match(/(\d{1,2}:\d{2})/)?.[1] ?? nsk;
}

export default function Header() {
  const { job, unreachable } = useJobStatus();
  const { theme, toggleTheme } = useTheme();
  const running = job?.status === "running";
  const bannedUntil = running && job ? job.banned_until_nsk : null;

  return (
    <header className="nav">
      <h1>Сервис анализа файлов</h1>
      <nav>
        <NavLink to="/">Скачивание</NavLink>
        <NavLink to="/files">Файлы и расчёты</NavLink>
      </nav>
      {unreachable && <span className="download-badge error-badge">Нет связи с backend</span>}
      {running && job && (
        <span
          className={`download-badge${bannedUntil ? " banned" : ""}`}
          title={`Старт (НСК): ${job.started_at_nsk}`}
        >
          <span className="pulse" />
          {bannedUntil
            ? `Бан, ждём до ${shortTime(bannedUntil)}`
            : `Идёт скачивание: ${job.files_downloaded} из ${job.names_received}`}
        </span>
      )}
      <button
        type="button"
        className="theme-toggle"
        onClick={toggleTheme}
        title="Переключить тему оформления"
      >
        {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
      </button>
    </header>
  );
}
