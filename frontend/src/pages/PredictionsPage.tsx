import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSports, fetchMatches } from "../api/client";
import MatchCard from "../components/MatchCard";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";

export default function PredictionsPage() {
  const [sport, setSport] = useState("all");

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: page, isLoading } = useQuery({
    queryKey: ["predictions-matches", sport],
    queryFn: () => fetchMatches({ sport: sport === "all" ? undefined : sport, days: 14, limit: 200 }),
    staleTime: 30_000,
  });

  const matches = (page?.matches ?? []).filter((m) => m.prediction !== null);

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      <h2 className="text-xl font-bold text-pi-primary font-display mb-4">All Predictions</h2>

      <div className="mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner size={40} />
        </div>
      ) : matches.length === 0 ? (
        <div className="text-center py-20 text-pi-muted">
          <p className="text-5xl mb-4">🔮</p>
          <p>No predictions available yet.</p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {matches.map((m) => (
            <MatchCard key={m.id} match={m} />
          ))}
        </div>
      )}
    </div>
  );
}
