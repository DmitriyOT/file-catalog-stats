import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import DownloadPage from "./pages/DownloadPage";
import FilesPage from "./pages/FilesPage";

export default function App() {
  return (
    <BrowserRouter>
      <header className="nav">
        <h1>Сервис анализа файлов</h1>
        <nav>
          <NavLink to="/">Скачивание</NavLink>
          <NavLink to="/files">Файлы и расчёты</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<DownloadPage />} />
          <Route path="/files" element={<FilesPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
