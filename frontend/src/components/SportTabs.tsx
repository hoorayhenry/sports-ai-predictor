import type { Sport } from "../api/types";

interface Props {
  sports: Sport[];
  selected: string;
  onSelect: (key: string) => void;
}

export default function SportTabs({ sports, selected, onSelect }: Props) {
  const all = [{ key: "all", name: "All", icon: "🌍", upcoming_matches: 0 }, ...sports];
  return (
    <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
      {all.map((s) => (
        <button
          key={s.key}
          onClick={() => onSelect(s.key)}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium whitespace-nowrap transition-all border ${
            selected === s.key
              ? "bg-sky-500/20 border-sky-500/50 text-sky-400"
              : "bg-[#1e293b] border-slate-700/50 text-slate-400 hover:text-white hover:border-slate-600"
          }`}
        >
          <span>{s.icon}</span>
          <span>{s.name}</span>
          {s.key !== "all" && s.upcoming_matches > 0 && (
            <span className="text-xs opacity-60">{s.upcoming_matches}</span>
          )}
        </button>
      ))}
    </div>
  );
}
