import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Header from "./components/Header";
import { JobStatusProvider } from "./components/JobStatusProvider";
import DownloadPage from "./pages/DownloadPage";
import FilesPage from "./pages/FilesPage";

export default function App() {
  return (
    <BrowserRouter>
      <JobStatusProvider>
        <Header />
        <main>
          <Routes>
            <Route path="/" element={<DownloadPage />} />
            <Route path="/files" element={<FilesPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </JobStatusProvider>
    </BrowserRouter>
  );
}
