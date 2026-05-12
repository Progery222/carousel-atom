import { Route, Routes } from "react-router-dom";
import StudioPage from "./pages/StudioPage";
import ApiDocsPage from "./pages/ApiDocsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<StudioPage />} />
      <Route path="/api-docs" element={<ApiDocsPage />} />
    </Routes>
  );
}
