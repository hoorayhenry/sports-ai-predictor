import { useState, useCallback } from "react";
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { RefreshCw, Clock, Tag, ChevronDown, ChevronUp, Newspaper, Trash2 } from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

interface NewsArticle {
  id: number;
  title: string;
  slug: string;
  source_url: string;
  source_name: string;
  category: string;
  summary: string;
  body: string | null;
  tags: string[] | null;
  published_at: string | null;
  created_at: string;
  image_url: string | null;
}

interface NewsPageData {
  articles: NewsArticle[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  drafts_pending: number;
}

const CATEGORIES = [
  { key: "all",               label: "All" },
  { key: "transfers",         label: "Transfers" },
  { key: "injuries",          label: "Injuries" },
  { key: "match-preview",     label: "Previews" },
  { key: "match-report",      label: "Results" },
  { key: "basketball",        label: "Basketball" },
  { key: "tennis",            label: "Tennis" },
  { key: "motorsport",        label: "F1" },
  { key: "cricket",           label: "Cricket" },
  { key: "rugby",             label: "Rugby" },
  { key: "american-football", label: "NFL" },
  { key: "general",           label: "General" },
];

// ── Default footballer hero images (shown when article has no og:image)
// None of these IDs are used as page hero backgrounds elsewhere in the app.
const DEFAULT_FOOTBALLER_IMAGES = [
  "https://images.unsplash.com/photo-1606925797300-0b35e9d1794e?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1489944440615-453fc2b6a9a9?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1543326727-cf6c39e8f84c?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1522778526097-ce0a22ceb253?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1486286701208-1d58e9338013?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1553778263-73a83bab9b0c?w=900&q=80&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1477281765962-ef34e8bb0967?w=900&q=80&auto=format&fit=crop",
];

// ── Inline paragraph images (different from default heroes above)
const INLINE_IMAGES: Record<string, string[]> = {
  football: [
    "https://images.unsplash.com/photo-1580647872851-54b4e97b4e7a?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1607962837359-5e7e89f86776?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1618886614638-80e3c103d465?w=900&q=80&auto=format&fit=crop",
  ],
  "match-preview": [
    "https://images.unsplash.com/photo-1506702315536-dd8b83e2dcf9?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?w=900&q=80&auto=format&fit=crop",
  ],
  "match-report": [
    "https://images.unsplash.com/photo-1580647872851-54b4e97b4e7a?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1607962837359-5e7e89f86776?w=900&q=80&auto=format&fit=crop",
  ],
  transfers: [
    "https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1618886614638-80e3c103d465?w=900&q=80&auto=format&fit=crop",
  ],
  injuries: [
    "https://images.unsplash.com/photo-1540420773420-3366772f4999?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1607962837359-5e7e89f86776?w=900&q=80&auto=format&fit=crop",
  ],
  basketball: [
    "https://images.unsplash.com/photo-1546519638-68e109498ffc?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1519861531473-9200262188bf?w=900&q=80&auto=format&fit=crop",
  ],
  tennis: [
    "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1542144582-1ba00456b5e3?w=900&q=80&auto=format&fit=crop",
  ],
  motorsport: [
    "https://images.unsplash.com/photo-1558981806-ec527fa84c39?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1541348263662-e068662d82af?w=900&q=80&auto=format&fit=crop",
  ],
  cricket: [
    "https://images.unsplash.com/photo-1540747913346-19212a4d2e69?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1629452791734-1943f065ceab?w=900&q=80&auto=format&fit=crop",
  ],
  rugby: [
    "https://images.unsplash.com/photo-1519766304817-4f37bda74a26?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1556056504-5c7696c4c28d?w=900&q=80&auto=format&fit=crop",
  ],
  "american-football": [
    "https://images.unsplash.com/photo-1566577739112-5180d4bf9390?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1534432182912-63863115e106?w=900&q=80&auto=format&fit=crop",
  ],
  general: [
    "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=900&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1476480862126-209bfaa8edc8?w=900&q=80&auto=format&fit=crop",
  ],
};

// ── Smart interlinking ─────────────────────────────────────────────
// Maps well-known club names / aliases → ESPN league slug (for /tables link)
const KNOWN_CLUBS: Record<string, string> = {
  // Premier League
  Arsenal: "eng.1", Chelsea: "eng.1", Liverpool: "eng.1",
  "Manchester City": "eng.1", "Man City": "eng.1",
  "Manchester United": "eng.1", "Man United": "eng.1", "Man Utd": "eng.1",
  "Tottenham": "eng.1", "Spurs": "eng.1",
  "Newcastle": "eng.1", "Newcastle United": "eng.1",
  "Aston Villa": "eng.1", "West Ham": "eng.1",
  "Brighton": "eng.1", "Everton": "eng.1",
  "Fulham": "eng.1", "Brentford": "eng.1",
  "Crystal Palace": "eng.1", "Nottingham Forest": "eng.1",
  "Wolverhampton": "eng.1", "Wolves": "eng.1",
  "Bournemouth": "eng.1", "Leicester": "eng.1", "Ipswich": "eng.1",
  "Southampton": "eng.1",
  // La Liga
  "Barcelona": "esp.1", "Barça": "esp.1",
  "Real Madrid": "esp.1", "Atlético Madrid": "esp.1", "Atletico Madrid": "esp.1",
  "Sevilla": "esp.1", "Valencia": "esp.1", "Villarreal": "esp.1",
  "Athletic Club": "esp.1", "Real Sociedad": "esp.1", "Betis": "esp.1",
  // Bundesliga
  "Bayern Munich": "ger.1", "Bayern": "ger.1",
  "Borussia Dortmund": "ger.1", "Dortmund": "ger.1", "BVB": "ger.1",
  "RB Leipzig": "ger.1", "Bayer Leverkusen": "ger.1", "Leverkusen": "ger.1",
  "Eintracht Frankfurt": "ger.1", "Wolfsburg": "ger.1",
  // Serie A
  "Juventus": "ita.1", "Juve": "ita.1",
  "Inter Milan": "ita.1", "Internazionale": "ita.1",
  "AC Milan": "ita.1", "Milan": "ita.1",
  "Napoli": "ita.1", "Roma": "ita.1", "Lazio": "ita.1",
  "Atalanta": "ita.1", "Fiorentina": "ita.1",
  // Ligue 1
  "PSG": "fra.1", "Paris Saint-Germain": "fra.1", "Paris SG": "fra.1",
  "Monaco": "fra.1", "Lyon": "fra.1", "Marseille": "fra.1", "Lille": "fra.1",
  // Champions League
  "Champions League": "uefa.champions",
  "Europa League": "uefa.europa",
  "Conference League": "uefa.europa.conf",
};

/**
 * Replace occurrences of entity names (from article tags) in text with
 * clickable links. Teams → /tables, multi-word non-clubs → player search.
 */
function linkifyParagraph(
  text: string,
  tags: string[],
): React.ReactNode[] {
  if (!tags.length) return [text];

  // Sort longest first to avoid partial matches inside longer names
  const sorted = [...new Set(tags)].sort((a, b) => b.length - a.length);
  const escaped = sorted.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const regex = new RegExp(`(${escaped.join("|")})`, "gi");

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const entity = match[1];
    const leagueSlug = Object.keys(KNOWN_CLUBS).find(
      (k) => k.toLowerCase() === entity.toLowerCase()
    );

    if (leagueSlug) {
      parts.push(
        <Link
          key={`${entity}-${match.index}`}
          to={`/tables?slug=${KNOWN_CLUBS[leagueSlug]}`}
          className="text-pi-indigo-light hover:underline font-semibold"
          onClick={(e) => e.stopPropagation()}
        >
          {entity}
        </Link>
      );
    } else if (entity.trim().includes(" ")) {
      // Multi-word non-club → treat as player name
      parts.push(
        <Link
          key={`${entity}-${match.index}`}
          to={`/player/search?name=${encodeURIComponent(entity)}`}
          className="text-amber-400/90 hover:underline font-semibold"
          onClick={(e) => e.stopPropagation()}
        >
          {entity}
        </Link>
      );
    } else {
      parts.push(entity);
    }
    lastIndex = match.index + entity.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}

/**
 * Render a tag pill: clickable if it maps to a club or player name.
 */
function TagPill({ tag }: { tag: string }) {
  const leagueKey = Object.keys(KNOWN_CLUBS).find(
    (k) => k.toLowerCase() === tag.toLowerCase()
  );
  const cls =
    "text-xs px-2.5 py-1 rounded-full bg-pi-surface border border-pi-border text-pi-secondary hover:border-pi-indigo/40 hover:text-pi-indigo-light transition-colors";

  if (leagueKey) {
    return (
      <Link to={`/tables?slug=${KNOWN_CLUBS[leagueKey]}`} className={cls}>
        {tag}
      </Link>
    );
  }
  if (tag.trim().includes(" ")) {
    return (
      <Link to={`/player/search?name=${encodeURIComponent(tag)}`} className={cls}>
        {tag}
      </Link>
    );
  }
  return <span className={cls}>{tag}</span>;
}

const catColors: Record<string, string> = {
  football:            "bg-sky-500/10 border-sky-500/25 text-sky-400",
  transfers:           "bg-amber-500/10 border-amber-500/25 text-amber-400",
  injuries:            "bg-rose-500/10 border-rose-500/25 text-rose-400",
  "match-preview":     "bg-violet-500/10 border-violet-500/25 text-violet-400",
  "match-report":      "bg-emerald-500/10 border-emerald-500/25 text-emerald-400",
  basketball:          "bg-orange-500/10 border-orange-500/25 text-orange-400",
  tennis:              "bg-lime-500/10 border-lime-500/25 text-lime-400",
  motorsport:          "bg-red-500/10 border-red-500/25 text-red-400",
  cricket:             "bg-yellow-500/10 border-yellow-500/25 text-yellow-400",
  rugby:               "bg-cyan-500/10 border-cyan-500/25 text-cyan-400",
  "american-football": "bg-purple-500/10 border-purple-500/25 text-purple-400",
  general:             "bg-indigo-500/10 border-indigo-500/25 text-indigo-300",
};

const catLabel: Record<string, string> = {
  "match-preview":     "Preview",
  "match-report":      "Result",
  "american-football": "NFL",
  "motorsport":        "F1",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3600000);
  const m = Math.floor(diff / 60000);
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${h}h ago`;
  if (m >= 1) return `${m}m ago`;
  return "just now";
}

function isWithin24h(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() < 86_400_000;
}

function getDefaultImage(article: NewsArticle): string {
  return DEFAULT_FOOTBALLER_IMAGES[article.id % DEFAULT_FOOTBALLER_IMAGES.length];
}

function getInlineImages(article: NewsArticle): [string, string] {
  const pool = INLINE_IMAGES[article.category] ?? INLINE_IMAGES.general;
  const idx = article.id % pool.length;
  return [pool[idx], pool[(idx + 1) % pool.length]];
}

function parseParagraphs(body: string | null): string[] {
  if (!body) return [];
  return body
    .split(/\n+/)
    .map((p) =>
      p.trim()
        .replace(/\*\*/g, "")
        .replace(/^#+\s*/, "")
        .replace(/^[-•*]\s*/, "")
        .replace(/^>\s*/, "")
    )
    .filter(
      (p) =>
        p.length > 30 &&
        !p.match(/^(headline|standfirst|tags|category|article body|source:|published)/i)
    );
}

function CatBadge({ category }: { category: string }) {
  const style = catColors[category] ?? catColors.general;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded-full border tracking-wider uppercase ${style}`}>
      {catLabel[category] ?? category}
    </span>
  );
}

// ── Article hero image — with footballer fallback ─────────────────
function ArticleImage({ article, height = "h-56" }: { article: NewsArticle; height?: string }) {
  const [imgFailed, setImgFailed] = useState(false);
  const src = (article.image_url && !imgFailed) ? article.image_url : getDefaultImage(article);

  return (
    <div className={`${height} rounded-t-2xl overflow-hidden bg-pi-surface`}>
      <img
        key={src}
        src={src}
        alt={article.title}
        className="w-full h-full object-cover object-top transition-transform duration-500 group-hover:scale-105"
        loading="lazy"
        onError={() => {
          if (!imgFailed) setImgFailed(true);
        }}
      />
    </div>
  );
}

// ── Featured article — tall card, full-width ──────────────────────
function FeaturedArticle({ article }: { article: NewsArticle }) {
  const [expanded, setExpanded] = useState(false);
  const [inline1Failed, setInline1Failed] = useState(false);
  const [inline2Failed, setInline2Failed] = useState(false);

  const paragraphs = parseParagraphs(article.body);
  const tags = article.tags ?? [];
  const [inlineImg1, inlineImg2] = getInlineImages(article);

  return (
    <div className="card overflow-hidden mb-6 group">
      <button className="w-full text-left" onClick={() => setExpanded((e) => !e)}>
        <ArticleImage article={article} height="h-72 md:h-96" />
        <div className="p-6 md:p-8">
          <div className="flex items-center gap-3 mb-4">
            <CatBadge category={article.category} />
            {isWithin24h(article.created_at) && (
              <span className="text-[11px] font-bold text-pi-emerald uppercase tracking-widest bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                Today
              </span>
            )}
            <span className="flex items-center gap-1.5 text-sm text-pi-muted/70 ml-auto">
              <Clock size={13} />
              {timeAgo(article.created_at)}
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </div>
          <h2 className="font-serif font-bold text-pi-primary text-[28px] md:text-[32px] leading-[1.15] mb-3 tracking-tight">
            {article.title}
          </h2>
          {!expanded && article.summary && (
            <p className="font-editorial text-[17px] text-pi-secondary leading-relaxed line-clamp-2">
              {article.summary}
            </p>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-6 md:px-8 pb-8 border-t border-pi-border/40 pt-5">
          {paragraphs.length > 0 ? (
            <div>
              {paragraphs.map((p, i) => (
                <div key={i}>
                  <p
                    className={`leading-[1.9] font-editorial mb-5 ${
                      i === 0
                        ? "text-[19px] font-semibold text-pi-primary"
                        : "text-[17px] text-pi-secondary"
                    }`}
                  >
                    {linkifyParagraph(p, tags)}
                  </p>
                  {i === 1 && !inline1Failed && (
                    <div className="my-6 rounded-xl overflow-hidden shadow-xl">
                      <img
                        src={inlineImg1}
                        alt=""
                        className="w-full h-56 md:h-72 object-cover"
                        loading="lazy"
                        onError={() => setInline1Failed(true)}
                      />
                    </div>
                  )}
                  {i === 3 && !inline2Failed && (
                    <div className="my-6 rounded-xl overflow-hidden shadow-xl">
                      <img
                        src={inlineImg2}
                        alt=""
                        className="w-full h-56 md:h-72 object-cover"
                        loading="lazy"
                        onError={() => setInline2Failed(true)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="font-editorial text-[17px] text-pi-secondary leading-[1.9]">
              {article.summary || "No content available."}
            </p>
          )}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-5 mt-2 border-t border-pi-border/30">
              <Tag size={13} className="text-pi-muted self-center" />
              {tags.map((tag) => (
                <TagPill key={tag} tag={tag} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Regular article card — compact, single row ────────────────────
function ArticleCard({ article }: { article: NewsArticle }) {
  const [expanded, setExpanded] = useState(false);
  const [inlineImgFailed, setInlineImgFailed] = useState(false);

  const paragraphs = parseParagraphs(article.body);
  const tags = article.tags ?? [];
  const [inlineImg] = getInlineImages(article);

  return (
    <div className={`card overflow-hidden flex flex-col transition-all duration-200 group ${expanded ? "border-pi-indigo/35" : ""}`}>
      <button className="w-full text-left flex flex-col md:flex-row" onClick={() => setExpanded((e) => !e)}>
        {/* Thumbnail — side-by-side on desktop */}
        <div className="md:w-56 md:shrink-0 h-48 md:h-auto overflow-hidden rounded-t-2xl md:rounded-l-2xl md:rounded-tr-none bg-pi-surface">
          <img
            src={article.image_url ?? getDefaultImage(article)}
            alt={article.title}
            className="w-full h-full object-cover object-top transition-transform duration-300 group-hover:scale-105"
            loading="lazy"
            onError={(e) => {
              const el = e.currentTarget;
              el.src = getDefaultImage(article);
            }}
          />
        </div>

        {/* Text */}
        <div className="p-5 flex-1">
          <div className="flex items-center gap-2 mb-3">
            <CatBadge category={article.category} />
            {isWithin24h(article.created_at) && (
              <span className="text-[10px] font-bold text-pi-emerald uppercase tracking-widest bg-emerald-500/10 px-1.5 py-0.5 rounded-full">
                Today
              </span>
            )}
            <span className="ml-auto flex items-center gap-1.5 text-sm text-pi-muted/60">
              <Clock size={12} />
              {timeAgo(article.created_at)}
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </span>
          </div>
          <h3 className="font-serif font-bold text-pi-primary text-[20px] leading-[1.25] mb-2 tracking-tight">
            {article.title}
          </h3>
          {!expanded && article.summary && (
            <p className="font-editorial text-[15px] text-pi-secondary leading-relaxed line-clamp-2">
              {article.summary}
            </p>
          )}
          <p className="text-sm text-pi-muted/50 mt-2">{article.source_name}</p>
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-5 border-t border-pi-border/40 pt-4">
          {paragraphs.length > 0 ? (
            <div>
              {paragraphs.map((p, i) => (
                <div key={i}>
                  <p className={`leading-[1.85] font-editorial mb-4 ${
                    i === 0 ? "text-[16px] font-semibold text-pi-primary" : "text-[15px] text-pi-secondary"
                  }`}>
                    {linkifyParagraph(p, tags)}
                  </p>
                  {i === 1 && !inlineImgFailed && (
                    <div className="my-4 rounded-xl overflow-hidden">
                      <img
                        src={inlineImg}
                        alt=""
                        className="w-full h-48 object-cover"
                        loading="lazy"
                        onError={() => setInlineImgFailed(true)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="font-editorial text-[15px] text-pi-secondary leading-relaxed">
              {article.summary || "No content available."}
            </p>
          )}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-3 border-t border-pi-border/30 mt-2">
              {tags.slice(0, 6).map((tag) => (
                <TagPill key={tag} tag={tag} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────
export default function NewsPage() {
  const [category, setCategory] = useState("all");
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const PAGE_SIZE = 10;

  // ── Infinite scroll query ────────────────────────────────────────
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteQuery<NewsPageData>({
    queryKey: ["news-infinite", category],
    queryFn: ({ pageParam = 0 }) =>
      api
        .get("/news", {
          params: {
            category: category === "all" ? undefined : category,
            limit: PAGE_SIZE,
            offset: pageParam,
          },
        })
        .then((r) => r.data),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
    staleTime: 120_000,
  });

  // ── Latest 24h articles (sidebar / strip) ────────────────────────
  const { data: latestData } = useQuery<NewsPageData>({
    queryKey: ["news-latest-24h"],
    queryFn: () =>
      api.get("/news", { params: { latest: true, limit: 8 } }).then((r) => r.data),
    staleTime: 60_000,
    refetchInterval: 300_000, // re-check every 5 min
  });

  // ── Infinite scroll sentinel (IntersectionObserver) ───────────────
  const observerRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
            fetchNextPage();
          }
        },
        { rootMargin: "300px" }
      );
      obs.observe(node);
      return () => obs.disconnect();
    },
    [hasNextPage, isFetchingNextPage, fetchNextPage]
  );

  // ── Refresh trigger ──────────────────────────────────────────────
  const trigger = useMutation({
    mutationFn: () => api.post("/news/trigger").then((r) => r.data),
    onSuccess: (triggerData) => {
      const before = triggerData?.published_before ?? 0;
      const drafts = triggerData?.drafts_pending ?? 0;
      setTimeout(async () => {
        const fresh = await refetch();
        const after = fresh.data?.pages[0]?.total ?? 0;
        const added = after - before;
        if (added > 0) setRefreshMsg(`+${added} new article${added !== 1 ? "s" : ""} published`);
        else if (drafts > 0) setRefreshMsg(`${drafts} queued — Gemini is rewriting`);
        else setRefreshMsg("Up to date");
        setTimeout(() => setRefreshMsg(null), 6000);
      }, 8000);
    },
  });

  // ── Reset (purge all, fetch fresh 20) ────────────────────────────
  const reset = useMutation({
    mutationFn: () => api.post("/news/reset").then((r) => r.data),
    onSuccess: (d) => {
      setRefreshMsg(`Wiped ${d.deleted} articles. Fetching 20 fresh ones…`);
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["news-infinite"] });
        queryClient.invalidateQueries({ queryKey: ["news-latest-24h"] });
        setRefreshMsg(null);
      }, 60_000);
    },
  });

  const allArticles = data?.pages.flatMap((p) => p.articles) ?? [];
  const [featured, ...rest] = allArticles;
  const total = data?.pages[0]?.total ?? 0;
  const latestArticles = latestData?.articles ?? [];
  const drafts_pending = data?.pages[0]?.drafts_pending ?? 0;

  return (
    <div className="min-h-screen pb-24 md:pb-8">
      {/* ── Hero ──────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-6">
        <img
          src="https://images.unsplash.com/photo-1459865264687-595d652de67e?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-center brightness-75 saturate-125 select-none pointer-events-none"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/25 to-[#070c19]/92" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/80 via-transparent to-transparent" />
        <div className="relative px-5 pt-8 pb-7 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="bg-sky-500/20 p-1.5 rounded-lg">
                <Newspaper size={16} className="text-pi-sky" />
              </div>
              <span className="section-label text-pi-sky/80">Sports Intelligence</span>
            </div>
            <h1 className="text-4xl md:text-5xl font-extrabold text-white font-display leading-none mb-2 drop-shadow-lg">
              Latest News
            </h1>
            <p className="text-white/70 text-base leading-relaxed mt-1">
              Football, basketball, tennis, F1 &amp; more · {total} articles
            </p>
          </div>
          <div className="flex flex-col items-end gap-2 mt-1 shrink-0">
            <button
              onClick={() => trigger.mutate()}
              disabled={trigger.isPending || reset.isPending}
              className="btn-ghost flex items-center gap-1.5"
            >
              <RefreshCw size={13} className={trigger.isPending ? "animate-spin" : ""} />
              {trigger.isPending ? "Fetching..." : "Refresh"}
            </button>
            <button
              onClick={() => {
                if (confirm("This will delete ALL articles and fetch 20 fresh ones from today. Continue?")) {
                  reset.mutate();
                }
              }}
              disabled={reset.isPending || trigger.isPending}
              className="flex items-center gap-1 text-xs text-pi-muted/50 hover:text-rose-400 transition-colors"
              title="Wipe all articles and fetch today's top 20"
            >
              <Trash2 size={11} /> Reset
            </button>
            {refreshMsg && (
              <span className="text-xs text-pi-emerald font-medium animate-fade-up max-w-[180px] text-right">
                {refreshMsg}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Centred content container ────────────────────────────── */}
      <div className="max-w-4xl mx-auto px-4">

        {/* ── Category filter pills ────────────────────────────────── */}
        <div className="flex gap-2 mb-5 flex-wrap">
          {CATEGORIES.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setCategory(key)}
              className={`px-4 py-1.5 text-sm font-semibold rounded-full border transition-all ${
                category === key ? "pill-active" : "pill-inactive"
              }`}
            >
              {label}
            </button>
          ))}
          {/* drafts_pending badge intentionally hidden — processing runs in background */}
        </div>

        {/* ── Latest 24h strip ─────────────────────────────────────── */}
        {latestArticles.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-pi-emerald animate-pulse" />
              <span className="text-sm font-bold text-pi-primary uppercase tracking-wider">Today</span>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-hide">
              {latestArticles.map((a) => (
                <div
                  key={a.id}
                  className="shrink-0 w-48 rounded-xl overflow-hidden border border-pi-border bg-pi-surface/40 cursor-default"
                >
                  <div className="h-24 overflow-hidden">
                    <img
                      src={a.image_url ?? getDefaultImage(a)}
                      alt={a.title}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={(e) => { e.currentTarget.src = getDefaultImage(a); }}
                    />
                  </div>
                  <div className="p-2.5">
                    <CatBadge category={a.category} />
                    <p className="font-serif text-[13px] font-semibold text-pi-primary leading-snug mt-1.5 line-clamp-2">
                      {a.title}
                    </p>
                    <p className="text-xs text-pi-muted/60 mt-1">{timeAgo(a.created_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Article list ─────────────────────────────────────────── */}
        {isLoading ? (
          <div className="flex justify-center py-20"><Spinner size={44} /></div>
        ) : allArticles.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-5xl mb-4">📰</p>
            <p className="text-lg text-pi-muted mb-3">No articles yet.</p>
            <p className="text-sm text-pi-muted/60 mb-6">Click "Refresh" to fetch today's sports news.</p>
            <button onClick={() => trigger.mutate()} className="btn-primary">Fetch News Now</button>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Featured article */}
            {featured && <FeaturedArticle key={featured.id} article={featured} />}

            {/* Rest as compact cards */}
            {rest.map((article) => (
              <ArticleCard key={article.id} article={article} />
            ))}

            {/* Infinite scroll sentinel */}
            <div ref={observerRef} className="h-16 flex items-center justify-center">
              {isFetchingNextPage && (
                <div className="flex items-center gap-3 text-sm text-pi-muted">
                  <Spinner size={20} />
                  Loading more…
                </div>
              )}
              {!hasNextPage && allArticles.length > 0 && (
                <p className="text-sm text-pi-muted/50">
                  You've read everything · {total} articles total
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
