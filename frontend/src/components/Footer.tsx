import logoUrl from "../assets/playsigma-logo.svg";

export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="hidden md:flex fixed bottom-0 left-0 right-0 z-40 items-center justify-between px-6 py-2.5 border-t border-pi-border/60 bg-pi-bg/95 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <img src={logoUrl} alt="PlaySigma" className="h-7 w-auto" />
        <span className="text-sm font-semibold text-pi-secondary tracking-wide">PlaySigma</span>
        <span className="text-pi-border/80 text-xs">·</span>
        <span className="text-xs text-pi-muted">Multi-sport intelligence platform</span>
      </div>

      <p className="text-xs text-pi-muted">
        For informational purposes only. Always bet responsibly.
      </p>

      <p className="text-xs text-pi-muted text-right">
        © {year} PlaySigma. All rights reserved.
      </p>
    </footer>
  );
}
