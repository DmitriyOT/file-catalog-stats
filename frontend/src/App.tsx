import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

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
          <Route path="/" element={<p>Страница скачивания (шаг 4)</p>} />
          <Route path="/files" element={<p>Страница файлов (шаг 5)</p>} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
