export function formatDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const isTomorrow = d.toDateString() === tomorrow.toDateString();

  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (isToday) return `Today ${time}`;
  if (isTomorrow) return `Tomorrow ${time}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + ` ${time}`;
}

export function outcomeLabel(market: string, outcome: string): string {
  const map: Record<string, Record<string, string>> = {
    h2h: { home: "Home Win", draw: "Draw", away: "Away Win" },
    totals: { over: "Over 2.5", under: "Under 2.5" },
    btts: { yes: "Both Score", no: "No Both" },
  };
  return map[market]?.[outcome] ?? `${market} ${outcome}`;
}

export function confidenceColor(conf: string): string {
  return conf === "high" ? "text-green-400" : conf === "medium" ? "text-yellow-400" : "text-slate-400";
}

export function resultLabel(result: string | null): string {
  if (result === "H") return "Home Win";
  if (result === "D") return "Draw";
  if (result === "A") return "Away Win";
  return "—";
}

export function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}
