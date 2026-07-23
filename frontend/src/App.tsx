import { BrowserRouter, Route, Routes } from "react-router-dom";
import Header from "./components/Header";
import DownloadPage from "./pages/DownloadPage";
import FilesPage from "./pages/FilesPage";

export default function App() {
  return (
    <BrowserRouter>
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<DownloadPage />} />
          <Route path="/files" element={<FilesPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
