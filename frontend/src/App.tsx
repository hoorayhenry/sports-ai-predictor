import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import HomePage from "./pages/HomePage";
import DailyPicksPage from "./pages/DailyPicksPage";
import SmartSetsPage from "./pages/SmartSetsPage";
import PerformancePage from "./pages/PerformancePage";
import HistoryPage from "./pages/HistoryPage";
import MatchDetailPage from "./pages/MatchDetailPage";
import NewsPage from "./pages/NewsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import StandingsPage from "./pages/StandingsPage";
import SportsPage from "./pages/SportsPage";
import LivePage from "./pages/LivePage";
import TeamDetailPage from "./pages/TeamDetailPage";
import PlayerDetailPage from "./pages/PlayerDetailPage";
import PlayerSearchPage from "./pages/PlayerSearchPage";
import SsTeamPage from "./pages/SsTeamPage";
import SsPlayerPage from "./pages/SsPlayerPage";

/** Ball that sweeps full-width across every page */
function AmbientBall() {
  return (
    <div
      className="fixed bottom-20 md:bottom-8 left-0 w-full pointer-events-none z-0 overflow-hidden"
      aria-hidden="true"
    >
      <span
        className="inline-block animate-ball-sweep text-[88px] select-none"
        style={{ filter: "drop-shadow(0 0 24px rgba(99,102,241,0.35))" }}
      >
        ⚽
      </span>
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col max-w-7xl mx-auto">
      <Navbar />
      <AmbientBall />
      <main className="flex-1 md:pt-2 md:pb-10 relative z-10">
        <Routes>
          <Route path="/"            element={<HomePage />} />
          <Route path="/picks"       element={<DailyPicksPage />} />
          <Route path="/sets"        element={<SmartSetsPage />} />
          <Route path="/news"        element={<NewsPage />} />
          <Route path="/analytics"   element={<AnalyticsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/history"     element={<HistoryPage />} />
          <Route path="/sports"      element={<SportsPage />} />
          <Route path="/tables"      element={<StandingsPage />} />
          <Route path="/live"                              element={<LivePage />} />
          <Route path="/match/:id"                         element={<MatchDetailPage />} />
          <Route path="/team/:leagueSlug/:teamId"          element={<TeamDetailPage />} />
          <Route path="/player/search"                     element={<PlayerSearchPage />} />
          <Route path="/player/soccer/:playerId"           element={<PlayerDetailPage />} />
          <Route path="/team/ss/:teamId"                   element={<SsTeamPage />} />
          <Route path="/player/ss/:playerId"               element={<SsPlayerPage />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
