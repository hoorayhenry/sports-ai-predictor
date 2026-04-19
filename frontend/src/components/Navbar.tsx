import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { Home, Flame, Target, BarChart2, History, Newspaper, Activity, Trophy, Radio, Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchLiveScores } from "../api/client";
import logoUrl from "../assets/playsigma-logo.svg";
import SearchBar from "./SearchBar";

const NAV = [
  { to: "/",            label: "Matches",  icon: Home },
  { to: "/live",        label: "Live",     icon: Radio },
  { to: "/picks",       label: "Picks",    icon: Flame },
  { to: "/sports",      label: "Sports",   icon: Trophy },
  { to: "/sets",        label: "Sets",     icon: Target },
  { to: "/news",        label: "News",     icon: Newspaper },
  { to: "/history",     label: "History",  icon: History },
  { to: "/performance", label: "Stats",    icon: BarChart2 },
  { to: "/analytics",   label: "Intel",    icon: Activity },
];

export default function Navbar() {
  const { pathname } = useLocation();
  const [searchOpen, setSearchOpen] = useState(false);

  const { data: liveData } = useQuery({
    queryKey: ["live-scores-nav"],
    queryFn: fetchLiveScores,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const liveCount = liveData?.matches?.length ?? 0;

  // Cmd/Ctrl+K opens search
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(s => !s);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  return (
    <>
      {/* ── Search overlay ────────────────────────────────── */}
      <SearchBar isOpen={searchOpen} onClose={() => setSearchOpen(false)} />

      {/* ── Desktop top bar ───────────────────────────────── */}
      <header className="hidden md:flex items-center justify-between px-6 py-3 navbar-glass sticky top-0 z-50">

        {/* Logo */}
        <Link to="/" className="flex items-center gap-0 group">
          <img
            src={logoUrl}
            alt="PlaySigma"
            className="h-8 w-auto logo-glow animate-float"
          />
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {NAV.map(({ to, label }) => {
            const active = pathname === to;
            return (
              <Link
                key={to}
                to={to}
                className={`relative px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                  active
                    ? "text-pi-primary"
                    : "text-pi-secondary hover:text-pi-primary hover:bg-pi-indigo/8"
                }`}
              >
                {label}
                {active && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 rounded-full bg-gradient-to-r from-pi-indigo to-pi-violet" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Right side: search + live pill */}
        <div className="flex items-center gap-2">
          {/* Search button */}
          <button
            onClick={() => setSearchOpen(true)}
            className="flex items-center gap-2 text-xs text-pi-muted bg-pi-surface/80 border border-pi-border/60 hover:border-pi-indigo/40 hover:text-pi-primary px-3 py-1.5 rounded-full transition-all"
          >
            <Search size={13} />
            <span>Search</span>
            <kbd className="text-[10px] text-pi-muted/50 border border-pi-border/40 px-1 py-0.5 rounded font-mono">⌘K</kbd>
          </button>

          {/* Live pill */}
          <Link to="/live" className="flex items-center gap-1.5 text-xs text-pi-secondary bg-pi-surface px-3 py-1.5 rounded-full border border-pi-border hover:border-pi-emerald/40 transition-colors">
            <span className="w-1.5 h-1.5 rounded-full bg-pi-emerald animate-pulse" />
            {liveCount > 0 ? (
              <><span className="font-semibold text-pi-emerald">{liveCount}</span> Live</>
            ) : (
              "Live"
            )}
          </Link>
        </div>
      </header>

      {/* ── Mobile bottom tab bar ─────────────────────────── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 navbar-glass border-t border-pi-border flex safe-bottom">
        {/* Search tap target — replaces one nav slot on mobile */}
        <button
          onClick={() => setSearchOpen(true)}
          className="flex-1 flex flex-col items-center justify-center py-2.5 gap-0.5 text-[11px] font-medium text-pi-muted transition-colors duration-200"
        >
          <Search size={17} strokeWidth={1.7} />
          <span>Search</span>
        </button>

        {NAV.slice(0, 8).map(({ to, label, icon: Icon }) => {
          const active = pathname === to;
          return (
            <Link
              key={to}
              to={to}
              className={`flex-1 flex flex-col items-center justify-center py-2.5 gap-0.5 text-[11px] font-medium transition-colors duration-200 ${
                active ? "text-pi-indigo-light" : "text-pi-muted"
              }`}
            >
              <Icon size={17} strokeWidth={active ? 2.2 : 1.7} />
              <span className={active ? "font-semibold" : ""}>{label}</span>
              {active && (
                <span className="absolute bottom-0 w-6 h-0.5 rounded-full bg-pi-indigo" />
              )}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
