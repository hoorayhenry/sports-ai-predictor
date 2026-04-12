import { Link, useLocation } from "react-router-dom";
import { TrendingUp, Zap, BarChart2, Home } from "lucide-react";

const NAV = [
  { to: "/", label: "Home", icon: Home },
  { to: "/predictions", label: "Predictions", icon: TrendingUp },
  { to: "/value-bets", label: "Value Bets", icon: Zap },
  { to: "/stats", label: "Stats", icon: BarChart2 },
];

export default function Navbar() {
  const { pathname } = useLocation();
  return (
    <>
      {/* Top bar — desktop only */}
      <header className="hidden md:flex items-center justify-between px-6 py-4 bg-[#1e293b] border-b border-slate-700/50">
        <Link to="/" className="flex items-center gap-2 text-xl font-bold text-white">
          <span className="text-2xl">⚽</span>
          <span className="text-sky-400">Sports</span>
          <span>AI</span>
        </Link>
        <nav className="flex items-center gap-1">
          {NAV.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
                pathname === to
                  ? "bg-sky-500/20 text-sky-400"
                  : "text-slate-400 hover:text-white hover:bg-slate-700/50"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>

      {/* Bottom tab bar — mobile */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-[#1e293b] border-t border-slate-700/50 flex">
        {NAV.map(({ to, label, icon: Icon }) => (
          <Link
            key={to}
            to={to}
            className={`flex-1 flex flex-col items-center justify-center py-2 gap-0.5 text-xs font-medium transition-colors ${
              pathname === to ? "text-sky-400" : "text-slate-500"
            }`}
          >
            <Icon size={20} />
            <span>{label}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
