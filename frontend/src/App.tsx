import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import HomePage from "./pages/HomePage";
import DailyPicksPage from "./pages/DailyPicksPage";
import SmartSetsPage from "./pages/SmartSetsPage";
import PerformancePage from "./pages/PerformancePage";
import HistoryPage from "./pages/HistoryPage";
import MatchDetailPage from "./pages/MatchDetailPage";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col max-w-7xl mx-auto">
      <Navbar />
      <main className="flex-1 md:pt-2">
        <Routes>
          <Route path="/"            element={<HomePage />} />
          <Route path="/picks"       element={<DailyPicksPage />} />
          <Route path="/sets"        element={<SmartSetsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/history"     element={<HistoryPage />} />
          <Route path="/match/:id"   element={<MatchDetailPage />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
