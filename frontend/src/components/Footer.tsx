import logoUrl from "../assets/hoorayhenry-logo.svg";

export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="hidden md:block border-t border-slate-700/40 bg-[#0a0f1e] mt-auto">
      <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <img src={logoUrl} alt="HoorayHenry" className="h-8 w-auto opacity-80" />
          <div>
            <p className="text-sm font-semibold text-white">Sports AI Predictor</p>
            <p className="text-xs text-slate-500">Autonomous · Multi-sport · Real-time intelligence</p>
          </div>
        </div>

        <p className="text-xs text-slate-500 text-center">
          For informational purposes only. Bet responsibly.
        </p>

        <div className="text-right">
          <p className="text-xs text-slate-400">
            Developed by <span className="text-sky-400 font-semibold">Henry Omoroje</span>
          </p>
          <p className="text-xs text-slate-600">© {year} HoorayHenry. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
