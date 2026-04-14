"""
Gemini Flash-powered NLP extraction for sports intelligence signals.

Uses Google Gemini 2.0 Flash — FREE tier: 1,500 requests/day, no credit card.
Get your key at: https://aistudio.google.com → "Get API key"

Given a news article text + team name, extracts:
  - Injuries (player, severity, impact score)
  - Suspensions (player, matches, impact score)
  - Player returns (positive impact)
  - Team morale signal
  - Overall team impact score (-1.0 to +1.0)
"""
from __future__ import annotations
import json
import httpx
from loguru import logger

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-flash-latest:generateContent?key={api_key}"
)

_PROMPT = """\
You are a sports intelligence analyst. Extract structured signals from the sports news article below.

Team in focus: {team_name}
Article text:
{text}

Return ONLY a JSON object with this exact structure:
{{
  "injuries": [
    {{"player": "Name", "severity": "out|doubtful|minor", "impact": -0.7}}
  ],
  "suspensions": [
    {{"player": "Name", "matches": 1, "impact": -0.6}}
  ],
  "returns": [
    {{"player": "Name", "impact": 0.4}}
  ],
  "morale": {{
    "score": 0.0,
    "reason": "brief reason or empty string"
  }},
  "overall_team_impact": 0.0,
  "confidence": 0.8
}}

Scoring rules:
- impact always between -1.0 and +1.0
- Key/star player injured/out = -0.7 to -0.9
- Important player doubtful = -0.4 to -0.6
- Fringe/backup player out = -0.1 to -0.3
- Key player returning from injury = +0.3 to +0.6
- Good team morale/winning run = +0.1 to +0.3
- Crisis/sacking/dressing room issues = -0.2 to -0.5
- overall_team_impact = weighted summary of all signals
- confidence = 0.1 if article is vague, 0.9 if very specific
- If no relevant signals found: empty lists, scores = 0.0, confidence = 0.1

Return ONLY valid JSON. No markdown, no explanation."""


def extract_signals(text: str, team_name: str, api_key: str) -> dict:
    """
    Extract intelligence signals from article text using Gemini Flash (free).
    Retries once on 429 rate limit. Falls back to empty signals on any error.
    """
    if not api_key or not text or not text.strip():
        return _empty()

    prompt  = _PROMPT.format(team_name=team_name, text=text[:2000])
    url     = _GEMINI_URL.format(api_key=api_key)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }

    for attempt in range(2):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)

            if resp.status_code == 429:
                if attempt == 0:
                    import time; time.sleep(5)
                    continue
                logger.debug(f"Gemini rate limit for {team_name} — skipping")
                return _empty()

            resp.raise_for_status()

            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

            if "```json" in raw:
                raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in raw:
                raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

            return _validate(json.loads(raw))

        except json.JSONDecodeError as e:
            logger.debug(f"NLP JSON parse error for {team_name}: {e}")
        except httpx.HTTPStatusError as e:
            logger.warning(f"Gemini API error for {team_name}: {e.response.status_code}")
        except Exception as e:
            logger.warning(f"NLP extraction failed for {team_name}: {e}")
        break

    return _empty()


def _validate(d: dict) -> dict:
    """Ensure all required keys exist with correct types."""
    out = _empty()
    out["injuries"]            = d.get("injuries", [])
    out["suspensions"]         = d.get("suspensions", [])
    out["returns"]             = d.get("returns", [])
    out["morale"]              = d.get("morale", {"score": 0.0, "reason": ""})
    out["overall_team_impact"] = float(d.get("overall_team_impact", 0.0))
    out["confidence"]          = float(d.get("confidence", 0.5))

    out["overall_team_impact"] = max(-1.0, min(1.0, out["overall_team_impact"]))
    out["confidence"]          = max(0.0,  min(1.0, out["confidence"]))
    return out


def _empty() -> dict:
    return {
        "injuries":            [],
        "suspensions":         [],
        "returns":             [],
        "morale":              {"score": 0.0, "reason": ""},
        "overall_team_impact": 0.0,
        "confidence":          0.0,
    }
