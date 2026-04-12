import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import HomePage from "./pages/HomePage";
import DailyPicksPage from "./pages/DailyPicksPage";
import SmartSetsPage from "./pages/SmartSetsPage";
import PerformancePage from "./pages/PerformancePage";
import MatchDetailPage from "./pages/MatchDetailPage";

export default function App() {
  return (
    <div className="max-w-4xl mx-auto">
      <Navbar />
      <main className="md:pt-2">
        <Routes>
          <Route path="/"            element={<HomePage />} />
          <Route path="/picks"       element={<DailyPicksPage />} />
          <Route path="/sets"        element={<SmartSetsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/match/:id"   element={<MatchDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
