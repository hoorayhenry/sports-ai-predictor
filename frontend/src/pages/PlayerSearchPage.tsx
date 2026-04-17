/**
 * PlayerSearchPage — resolves a player name to an ESPN athlete ID.
 * Used for smart article interlinking: clicking a player name tag
 * lands here, we do a quick ESPN search, and redirect automatically.
 */
import { useEffect } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { User, Search } from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

interface SearchResult {
  id: string;
  name: string;
  team: string;
  position: string;
  image: string;
}

export default function PlayerSearchPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const name = params.get("name") || "";

  const { data, isLoading, isError } = useQuery<{ results: SearchResult[] }>({
    queryKey: ["player-search", name],
    queryFn: () =>
      api.get(`/players/soccer/search?q=${encodeURIComponent(name)}`).then(r => r.data),
    enabled: !!name,
    staleTime: 1800_000,
    retry: 1,
  });

  // Auto-redirect if exactly 1 result
  useEffect(() => {
    if (data?.results?.length === 1) {
      navigate(`/player/soccer/${data.results[0].id}`, { replace: true });
    }
  }, [data, navigate]);

  if (!name) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 px-6">
        <Search size={36} className="text-pi-muted" />
        <p className="font-display text-xl font-bold text-pi-primary">No player name provided</p>
        <Link to="/news" className="btn-secondary">Back to News</Link>
      </div>
    );
  }

  if (isLoading || (data?.results?.length === 1)) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <Spinner size={44} />
        <p className="text-sm text-pi-muted">
          {data?.results?.length === 1 ? `Loading ${data.results[0].name}…` : `Searching for "${name}"…`}
        </p>
      </div>
    );
  }

  if (isError || !data?.results.length) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 px-6 text-center">
        <User size={40} className="text-pi-muted" />
        <p className="font-display text-xl font-bold text-pi-primary">Player Not Found</p>
        <p className="text-sm text-pi-muted max-w-xs">
          No ESPN athlete found for "{name}". They may be inactive or the name may be abbreviated.
        </p>
        <Link to="/news" className="btn-secondary">Back to News</Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen pb-24 md:pb-8 px-4 pt-6">
      <div className="max-w-lg mx-auto">
        <div className="mb-5">
          <h1 className="text-2xl font-extrabold text-pi-primary font-display mb-1">
            Search Results
          </h1>
          <p className="text-sm text-pi-muted">
            {data.results.length} athletes found for "{name}"
          </p>
        </div>

        <div className="space-y-3">
          {data.results.map((result) => (
            <Link
              key={result.id}
              to={`/player/soccer/${result.id}`}
              className="flex items-center gap-4 card p-4 hover:border-pi-indigo/35 group"
            >
              <div className="w-12 h-12 rounded-full overflow-hidden bg-pi-surface border border-pi-border/30 shrink-0">
                {result.image ? (
                  <img
                    src={result.image}
                    alt={result.name}
                    className="w-full h-full object-cover"
                    onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <User size={18} className="text-pi-muted" />
                  </div>
                )}
              </div>
              <div className="flex-1">
                <p className="font-semibold text-pi-primary group-hover:text-pi-indigo-light transition-colors">
                  {result.name}
                </p>
                <p className="text-xs text-pi-muted">
                  {result.team || "Free agent"}
                  {result.position ? ` · ${result.position}` : ""}
                </p>
              </div>
              <span className="text-pi-indigo-light/50 text-xs">View →</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
