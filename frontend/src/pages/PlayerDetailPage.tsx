import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, User, Flag, BarChart2, Newspaper,
} from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

interface PlayerData {
  id: string;
  name: string;
  first_name: string;
  last_name: string;
  shirt_number?: string | number;
  position: string;
  position_abbr: string;
  nationality: string;
  nationality_flag?: string;
  age?: number;
  dob: string;
  headshot: string;
  height?: string;
  weight?: string;
  team: { id: string; name: string; logo: string; league_slug?: string };
  stats: { name: string; display_value: string }[];
  career: { season: string; stats: { name: string; display_value: string }[] }[];
  cached?: boolean;
}

interface NewsArticle {
  id: number;
  title: string;
  summary: string;
  category: string;
  image_url: string | null;
  published_at: string | null;
  created_at: string;
}

type Tab = "bio" | "stats" | "news";

const STAT_ICONS: Record<string, string> = {
  appearances: "▶", goals: "⚽", assists: "🎯", saves: "🧤",
  "yellow cards": "🟨", "red cards": "🟥", "clean sheets": "🛡️",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function formatDob(dob: string): string {
  if (!dob) return "—";
  const d = new Date(dob);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatBadge({ name, value }: { name: string; value: string }) {
  const icon = STAT_ICONS[name.toLowerCase()] || "•";
  return (
    <div className="card p-3 text-center">
      <p className="text-2xl mb-1">{icon}</p>
      <p className="text-xl font-bold text-pi-primary tabular-nums">{value}</p>
      <p className="text-[11px] text-pi-muted capitalize mt-0.5">{name}</p>
    </div>
  );
}

function BioRow({ label, value }: { label: string; value?: string | number | null }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between py-2.5 border-b border-pi-border/15">
      <span className="text-xs text-pi-muted w-32 shrink-0">{label}</span>
      <span className="text-sm font-semibold text-pi-primary text-right">{value}</span>
    </div>
  );
}

function NewsCard({ article }: { article: NewsArticle }) {
  return (
    <Link
      to="/news"
      className="flex gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.025] hover:bg-white/[0.05] hover:border-pi-indigo/30 transition-all group"
    >
      {article.image_url && (
        <img
          src={article.image_url}
          alt=""
          className="w-20 h-14 object-cover rounded-lg shrink-0"
          onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      )}
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-pi-primary text-sm leading-snug line-clamp-2 group-hover:text-pi-indigo-light transition-colors">
          {article.title}
        </p>
        <p className="text-[11px] text-pi-muted mt-1">
          {article.category} · {timeAgo(article.created_at)}
        </p>
      </div>
    </Link>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

// ── Headshot URL cascade ───────────────────────────────────────────────────────
// ESPN CDN has two URL patterns; try both before falling back to the silhouette.
function headshotUrls(playerId: string, apiHeadshot?: string): string[] {
  const urls: string[] = [];
  if (apiHeadshot) urls.push(apiHeadshot);
  urls.push(`https://a.espncdn.com/i/headshots/soccer/players/full/${playerId}.png`);
  urls.push(`https://a.espncdn.com/combiner/i?img=/i/headshots/soccer/players/full/${playerId}.png&w=350&h=254`);
  return [...new Set(urls)];
}

export default function PlayerDetailPage() {
  const { playerId } = useParams<{ playerId: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("bio");
  const [imgAttempt, setImgAttempt] = useState(0);

  const { data: player, isLoading, isError } = useQuery<PlayerData>({
    queryKey: ["player", playerId],
    queryFn: () =>
      api.get(`/players/soccer/${playerId}`).then(r => r.data),
    enabled: !!playerId,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery<{ articles: NewsArticle[] }>({
    queryKey: ["player-news", playerId, player?.name],
    queryFn: () =>
      api.get(`/players/soccer/${playerId}/news?player_name=${encodeURIComponent(player!.name)}`).then(r => r.data),
    enabled: !!player?.name && tab === "news",
    staleTime: 120_000,
    retry: 1,
  });

  // ── Loading / error ────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner size={44} />
      </div>
    );
  }

  if (isError || !player) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 px-6">
        <User size={40} className="text-pi-muted" />
        <p className="font-display text-xl font-bold text-pi-primary">Player Not Found</p>
        <p className="text-sm text-pi-muted text-center max-w-xs">
          Could not load player data from ESPN. The player ID may be incorrect or the player may no longer be active.
        </p>
        <button onClick={() => navigate(-1)} className="btn-secondary">
          Go back
        </button>
      </div>
    );
  }

  // ── Position color ─────────────────────────────────────────────────────────
  const posColors: Record<string, string> = {
    GK: "#f59e0b", D: "#3b82f6", M: "#10b981", F: "#f43f5e",
  };
  const posColor = posColors[player.position_abbr] || "#6366f1";

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "bio",   label: "Bio",   icon: <Flag size={14} /> },
    { key: "stats", label: "Stats", icon: <BarChart2 size={14} /> },
    { key: "news",  label: "News",  icon: <Newspaper size={14} /> },
  ];

  return (
    <div className="min-h-screen pb-24 md:pb-8">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-0"
        style={{
          background: `linear-gradient(135deg, ${posColor}33 0%, #070c19 70%)`,
          minHeight: 220,
          borderBottom: `2px solid ${posColor}44`,
        }}
      >
        <div className="absolute inset-0 bg-[#070c19]/60" />

        {/* Back button */}
        <button
          onClick={() => window.history.length > 1 ? navigate(-1) : navigate("/")}
          className="absolute top-4 left-4 z-10 flex items-center gap-1.5 text-sm text-white/80 hover:text-white transition-colors bg-black/40 backdrop-blur-sm px-4 py-2 rounded-full border border-white/15 hover:border-white/30"
        >
          <ArrowLeft size={15} />
          Back
        </button>

        <div className="relative z-10 px-5 pt-14 pb-0 flex items-end gap-4">
          {/* Headshot */}
          {(() => {
            const urls = headshotUrls(playerId!, player.headshot);
            const currentSrc = urls[imgAttempt];
            const allFailed = imgAttempt >= urls.length;
            return (
              <div
                className="w-28 h-28 rounded-2xl overflow-hidden shrink-0 shadow-2xl border-2 flex items-end justify-center"
                style={{ borderColor: `${posColor}66`, background: `linear-gradient(145deg, ${posColor}33, ${posColor}11)` }}
              >
                {!allFailed && currentSrc ? (
                  <img
                    src={currentSrc}
                    alt={player.name}
                    className="w-full h-full object-cover object-top"
                    onError={() => setImgAttempt(a => a + 1)}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <User size={40} className="text-white/25" />
                  </div>
                )}
              </div>
            );
          })()}

          {/* Name + details */}
          <div className="flex-1 min-w-0 pb-4">
            {/* Position badge */}
            <span
              className="inline-block text-[10px] font-bold uppercase tracking-widest px-2.5 py-0.5 rounded-full mb-1.5"
              style={{ background: `${posColor}33`, color: posColor }}
            >
              {player.position || player.position_abbr}
            </span>

            <h1 className="text-2xl md:text-3xl font-extrabold text-white font-display leading-tight drop-shadow-lg">
              {player.name}
            </h1>

            {/* Team + shirt number */}
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              {player.team?.name && (
                <span className="text-xs font-semibold text-white/60 flex items-center gap-1.5">
                  {player.team.logo && (
                    <img src={player.team.logo} alt="" className="w-4 h-4 object-contain" />
                  )}
                  {player.team.name}
                </span>
              )}
              {player.shirt_number && (
                <span className="text-xs font-bold text-white/40">
                  #{player.shirt_number}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div className="relative z-10 px-5 flex gap-1 border-t border-white/10 mt-2">
          {TABS.map(({ key, label, icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-4 py-3 text-xs font-semibold transition-all border-b-2 ${
                tab === key
                  ? "border-white text-white"
                  : "border-transparent text-white/40 hover:text-white/70"
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab content ─────────────────────────────────────────────────── */}
      <div className="px-4 pt-5">

        {/* Bio ──────────────────────────────────────────────────────────── */}
        {tab === "bio" && (
          <div className="max-w-lg mx-auto space-y-4">
            <div className="card p-5">
              <BioRow label="Nationality"   value={player.nationality} />
              <BioRow label="Date of Birth" value={formatDob(player.dob)} />
              <BioRow label="Age"           value={player.age ? `${player.age} years` : undefined} />
              <BioRow label="Height"        value={player.height} />
              <BioRow label="Weight"        value={player.weight} />
              <BioRow label="Position"      value={player.position} />
              <BioRow label="Shirt Number"  value={player.shirt_number} />
            </div>

            {/* Current club */}
            {(player.team?.name || player.team?.logo) && (() => {
              const hasLink = player.team.league_slug && player.team.id;
              const inner = (
                <div className={`card p-4 flex items-center gap-4 ${hasLink ? "hover:border-pi-indigo/35" : ""}`}>
                  {player.team.logo && (
                    <img
                      src={player.team.logo}
                      alt={player.team.name}
                      className="w-10 h-10 object-contain"
                      onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  )}
                  <div>
                    <p className="text-xs text-pi-muted">Current Club</p>
                    <p className="font-bold text-pi-primary text-sm">{player.team.name || "—"}</p>
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-[11px] text-pi-muted bg-pi-surface px-2 py-1 rounded-full border border-pi-border/30">
                      Active
                    </span>
                    {hasLink && <span className="text-pi-indigo-light/50 text-xs">→</span>}
                  </div>
                </div>
              );
              return hasLink ? (
                <Link to={`/team/${player.team.league_slug}/${player.team.id}`}>{inner}</Link>
              ) : inner;
            })()}

            <p className="text-[11px] text-pi-muted/50 text-center">
              Data from ESPN · updates automatically on transfers
            </p>
          </div>
        )}

        {/* Stats ────────────────────────────────────────────────────────── */}
        {tab === "stats" && (
          <div className="max-w-lg mx-auto">
            {player.stats.length === 0 ? (
              <div className="card p-8 text-center">
                <BarChart2 size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Stats Available</p>
                <p className="text-sm text-pi-muted">
                  ESPN doesn't have current season stats for this player yet.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  {player.stats.slice(0, 9).map((s, i) => (
                    <StatBadge key={i} name={s.name} value={s.display_value} />
                  ))}
                </div>

                {/* Career history */}
                {player.career.length > 0 && (
                  <div>
                    <h3 className="section-label text-pi-muted mb-3 px-1">Career History</h3>
                    <div className="space-y-2">
                      {player.career.map((c, i) => (
                        <div key={i} className="card p-3">
                          <p className="text-xs font-bold text-pi-secondary mb-2">{c.season}</p>
                          <div className="flex flex-wrap gap-3">
                            {c.stats.slice(0, 6).map((s, j) => (
                              <div key={j} className="text-center">
                                <p className="text-sm font-bold text-pi-primary tabular-nums">{s.display_value}</p>
                                <p className="text-[10px] text-pi-muted capitalize">{s.name}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* News ─────────────────────────────────────────────────────────── */}
        {tab === "news" && (
          <div className="max-w-lg mx-auto">
            {newsLoading ? (
              <div className="flex flex-col items-center py-20 gap-3">
                <Spinner size={40} />
                <p className="text-xs text-pi-muted">Loading news…</p>
              </div>
            ) : !newsData?.articles.length ? (
              <div className="card p-8 text-center">
                <Newspaper size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Articles Yet</p>
                <p className="text-sm text-pi-muted">
                  No published articles mention {player.name} yet. Check back after the next news cycle.
                </p>
                <Link to="/news" className="mt-4 inline-block btn-secondary text-xs">
                  Browse all news
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {newsData.articles.map(a => (
                  <NewsCard key={a.id} article={a} />
                ))}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
