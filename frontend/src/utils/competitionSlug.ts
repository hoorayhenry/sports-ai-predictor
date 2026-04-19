/**
 * Maps competition names (as they appear in match data) to the league slug
 * used by the StandingsPage (/tables?slug=<slug>).
 *
 * Covers all leagues in StandingsPage LEAGUES array plus common API aliases.
 */
const MAP: Record<string, string> = {
  // English
  "premier league":          "eng.1",
  "epl":                     "eng.1",
  // Spanish
  "la liga":                 "esp.1",
  "laliga":                  "esp.1",
  // German
  "bundesliga":              "ger.1",
  "fußball-bundesliga":      "ger.1",
  // Italian
  "serie a":                 "ita.1",
  // French
  "ligue 1":                 "fra.1",
  "ligue 1 uber eats":       "fra.1",
  // Portuguese
  "primeira liga":           "por.1",
  "liga portugal":           "por.1",
  // Dutch
  "eredivisie":              "ned.1",
  // Turkish
  "süper lig":               "tur.1",
  "super lig":               "tur.1",
  // Scottish
  "scottish prem.":          "sco.1",
  "scottish premiership":    "sco.1",
  "scottish premier league": "sco.1",
  // Belgian
  "pro league":              "bel.1",
  "jupiler pro league":      "bel.1",
  // US / Americas
  "mls":                     "usa.1",
  "major league soccer":     "usa.1",
  "brasileirão":             "bra.1",
  "série a":                 "bra.1",
  "campeonato brasileiro":   "bra.1",
  "liga profesional":        "arg.1",
  "liga profesional argentina": "arg.1",
  "liga betplay":            "col.1",
  // European cups
  "champions league":        "uefa.champions",
  "uefa champions league":   "uefa.champions",
  "europa league":           "uefa.europa",
  "uefa europa league":      "uefa.europa",
  "conference league":       "uefa.europa.conf",
  "uefa conference league":  "uefa.europa.conf",
};

/**
 * Returns the StandingsPage slug for a given competition name, or null
 * if the competition is not in our standings coverage.
 */
export function getCompetitionSlug(competition: string): string | null {
  if (!competition) return null;
  return MAP[competition.toLowerCase().trim()] ?? null;
}
