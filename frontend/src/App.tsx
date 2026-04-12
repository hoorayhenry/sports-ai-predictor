import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import HomePage from "./pages/HomePage";
import PredictionsPage from "./pages/PredictionsPage";
import ValueBetsPage from "./pages/ValueBetsPage";
import MatchDetailPage from "./pages/MatchDetailPage";
import StatsPage from "./pages/StatsPage";

export default function App() {
  return (
    <div className="max-w-4xl mx-auto">
      <Navbar />
      <main className="md:pt-2">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/predictions" element={<PredictionsPage />} />
          <Route path="/value-bets" element={<ValueBetsPage />} />
          <Route path="/match/:id" element={<MatchDetailPage />} />
          <Route path="/stats" element={<StatsPage />} />
        </Routes>
      </main>
    </div>
  );
}
