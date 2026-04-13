"""
Claude Haiku-powered NLP extraction for sports intelligence signals.

Given a news article text + team name, extracts:
  - Injuries (player, severity, impact score)
  - Suspensions (player, matches, impact score)
  - Player returns (positive impact)
  - Team morale signal
  - Overall team impact score (-1.0 to +1.0)

Uses claude-haiku-4-5-20251001 for low cost and fast response (~50ms).
"""
from __future__ import annotations
import json
from loguru import logger

try:
    import anthropic as _anthropic_lib
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False
    logger.warning("anthropic package not installed — NLP extraction disabled")

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
    Extract intelligence signals from article text using Claude Haiku.
    Returns structured signal dict. Falls back to empty signals on any error.
    """
    if not _ANTHROPIC_OK or not api_key or not text or not text.strip():
        return _empty()

    try:
        client = _anthropic_lib.Anthropic(api_key=api_key)
        truncated = text[:2000]

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(team_name=team_name, text=truncated),
            }],
        )

        raw = msg.content[0].text.strip()

        # Strip markdown fences if present
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

        result = json.loads(raw)
        return _validate(result)

    except json.JSONDecodeError as e:
        logger.debug(f"NLP JSON parse error for {team_name}: {e}")
    except Exception as e:
        logger.warning(f"NLP extraction failed for {team_name}: {e}")

    return _empty()


def _validate(d: dict) -> dict:
    """Ensure all required keys exist with correct types."""
    out = _empty()
    out["injuries"]   = d.get("injuries", [])
    out["suspensions"] = d.get("suspensions", [])
    out["returns"]    = d.get("returns", [])
    out["morale"]     = d.get("morale", {"score": 0.0, "reason": ""})
    out["overall_team_impact"] = float(d.get("overall_team_impact", 0.0))
    out["confidence"]          = float(d.get("confidence", 0.5))

    # Clamp values
    out["overall_team_impact"] = max(-1.0, min(1.0, out["overall_team_impact"]))
    out["confidence"]          = max(0.0,  min(1.0, out["confidence"]))
    return out


def _empty() -> dict:
    return {
        "injuries":           [],
        "suspensions":        [],
        "returns":            [],
        "morale":             {"score": 0.0, "reason": ""},
        "overall_team_impact": 0.0,
        "confidence":          0.0,
    }
