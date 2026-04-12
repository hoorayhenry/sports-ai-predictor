"""
Daily email automation — sends AI Daily Picks + Smart Sets via SMTP.
Supports Gmail SMTP, any standard SMTP server, or SendGrid API.
"""
from __future__ import annotations
import smtplib
import json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from loguru import logger

from config.settings import get_settings

settings = get_settings()


# ── HTML template helpers ─────────────────────────────────────────────

def _decision_badge(decision: str) -> str:
    if decision == "PLAY":
        return '<span style="background:#16a34a;color:#fff;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:700;">✅ PLAY</span>'
    return '<span style="background:#dc2626;color:#fff;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:700;">❌ SKIP</span>'


def _prob_tag_badge(tag: str) -> str:
    colors = {"HIGH": "#16a34a", "MEDIUM": "#ca8a04", "RISKY": "#dc2626"}
    emoji  = {"HIGH": "🟢", "MEDIUM": "🟡", "RISKY": "🔴"}
    bg = colors.get(tag, "#6b7280")
    em = emoji.get(tag, "⚪")
    return f'<span style="background:{bg};color:#fff;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;">{em} {tag}</span>'


def _outcome_label(outcome: str) -> str:
    return {"H": "Home Win", "D": "Draw", "A": "Away Win",
            "over": "Over 2.5", "under": "Under 2.5",
            "yes": "Both Score", "no": "No BTTS"}.get(outcome, outcome)


def _build_html(daily_picks: list[dict], smart_sets: list[dict]) -> str:
    today_str = datetime.utcnow().strftime("%A, %d %B %Y")

    # ── Daily Picks table ──
    picks_rows = ""
    for i, p in enumerate(daily_picks[:10], 1):
        conf_color = "#16a34a" if p["confidence_score"] >= 75 else (
            "#ca8a04" if p["confidence_score"] >= 60 else "#dc2626"
        )
        picks_rows += f"""
        <tr style="background:{'#1e293b' if i%2==0 else '#0f172a'}">
          <td style="padding:10px 12px;font-size:13px;color:#94a3b8;">{i}</td>
          <td style="padding:10px 12px;font-size:13px;color:#e2e8f0;">
            {p.get('sport_icon','🏆')} <strong>{p['home_team']}</strong> vs <strong>{p['away_team']}</strong><br>
            <span style="color:#64748b;font-size:11px;">{p.get('competition','')}</span>
          </td>
          <td style="padding:10px 12px;text-align:center;">{_prob_tag_badge(p.get('prob_tag','RISKY'))}</td>
          <td style="padding:10px 12px;text-align:center;color:#38bdf8;font-weight:700;font-size:14px;">
            {_outcome_label(p.get('predicted_outcome',''))}
          </td>
          <td style="padding:10px 12px;text-align:center;font-weight:700;font-size:15px;color:{conf_color};">
            {p.get('confidence_score', 0):.0f}
          </td>
          <td style="padding:10px 12px;text-align:center;">{_decision_badge(p.get('ai_decision','SKIP'))}</td>
          <td style="padding:10px 12px;text-align:center;color:#fbbf24;font-weight:600;">
            {p.get('top_prob', 0)*100:.0f}%
          </td>
        </tr>"""

    # ── Smart Sets blocks ──
    sets_html = ""
    for ss in smart_sets[:10]:
        matches_data = ss.get("matches", [])
        match_rows = ""
        for m in matches_data:
            match_rows += f"""
            <tr>
              <td style="padding:6px 10px;color:#cbd5e1;font-size:12px;">
                {m.get('sport_icon','🏆')} {m['home_team']} vs {m['away_team']}
              </td>
              <td style="padding:6px 10px;color:#38bdf8;font-size:12px;text-align:center;">
                {_outcome_label(m.get('predicted_outcome',''))}
              </td>
              <td style="padding:6px 10px;color:#fbbf24;font-size:12px;text-align:right;font-weight:600;">
                {m.get('top_prob',0)*100:.0f}%
              </td>
            </tr>"""
        conf = ss.get("overall_confidence", 0)
        conf_color = "#16a34a" if conf >= 75 else ("#ca8a04" if conf >= 60 else "#dc2626")
        sets_html += f"""
        <div style="margin-bottom:20px;background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">
          <div style="background:#0f172a;padding:10px 16px;display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:700;color:#e2e8f0;">Set #{ss['set_number']}</span>
            <span>
              <span style="color:{conf_color};font-weight:700;font-size:14px;">Conf: {conf:.0f}</span>
              &nbsp;&nbsp;
              <span style="color:#94a3b8;font-size:12px;">{ss['match_count']} matches</span>
            </span>
          </div>
          <table width="100%" cellpadding="0" cellspacing="0">
            <thead>
              <tr style="background:#1a2744;">
                <th style="padding:6px 10px;text-align:left;color:#64748b;font-size:11px;font-weight:600;">MATCH</th>
                <th style="padding:6px 10px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">PICK</th>
                <th style="padding:6px 10px;text-align:right;color:#64748b;font-size:11px;font-weight:600;">PROB</th>
              </tr>
            </thead>
            <tbody>{match_rows}</tbody>
          </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:Inter,system-ui,sans-serif;">
  <div style="max-width:650px;margin:0 auto;padding:20px;">

    <!-- Header -->
    <div style="text-align:center;padding:30px 0 20px;">
      <h1 style="margin:0;font-size:28px;font-weight:800;color:#e2e8f0;">
        ⚽ Sports <span style="color:#38bdf8;">AI</span> Predictor
      </h1>
      <p style="margin:8px 0 0;color:#64748b;font-size:14px;">Daily Report — {today_str}</p>
    </div>

    <!-- Daily Picks -->
    <div style="margin-bottom:30px;background:#1e293b;border-radius:16px;overflow:hidden;border:1px solid #334155;">
      <div style="background:linear-gradient(135deg,#0369a1,#0ea5e9);padding:16px 20px;">
        <h2 style="margin:0;font-size:18px;font-weight:700;color:#fff;">🔥 AI Daily Picks</h2>
        <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:13px;">Top-ranked matches for today & tomorrow</p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <thead>
          <tr style="background:#1a2744;border-bottom:1px solid #334155;">
            <th style="padding:10px 12px;text-align:left;color:#64748b;font-size:11px;font-weight:600;">#</th>
            <th style="padding:10px 12px;text-align:left;color:#64748b;font-size:11px;font-weight:600;">MATCH</th>
            <th style="padding:10px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">TAG</th>
            <th style="padding:10px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">PICK</th>
            <th style="padding:10px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">CONF</th>
            <th style="padding:10px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">DECISION</th>
            <th style="padding:10px 12px;text-align:center;color:#64748b;font-size:11px;font-weight:600;">PROB</th>
          </tr>
        </thead>
        <tbody>{picks_rows}</tbody>
      </table>
    </div>

    <!-- Smart Sets -->
    <div style="margin-bottom:20px;">
      <div style="background:linear-gradient(135deg,#7c3aed,#a855f7);padding:16px 20px;border-radius:12px 12px 0 0;">
        <h2 style="margin:0;font-size:18px;font-weight:700;color:#fff;">🎯 Smart Sets (10)</h2>
        <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:13px;">Curated 10-match packages — mixed sports, balanced risk</p>
      </div>
      {sets_html}
    </div>

    <!-- Footer -->
    <div style="text-align:center;padding:20px 0;color:#475569;font-size:12px;border-top:1px solid #1e293b;">
      <p style="margin:0;">Generated by Sports AI Predictor • {today_str}</p>
      <p style="margin:6px 0 0;color:#334155;">For informational purposes only. Bet responsibly.</p>
    </div>
  </div>
</body>
</html>"""
    return html


# ── Send email ────────────────────────────────────────────────────────

def send_daily_email(
    daily_picks: list[dict],
    smart_sets: list[dict],
    recipient: Optional[str] = None,
) -> bool:
    """
    Send the daily report email.
    Returns True if sent successfully, False otherwise.
    """
    to_addr = recipient or settings.email_recipient
    if not to_addr:
        logger.warning("No email recipient configured — skipping daily email")
        return False

    if not settings.email_smtp_host:
        logger.warning("No SMTP host configured — skipping daily email")
        return False

    today_str = datetime.utcnow().strftime("%d %b %Y")
    subject   = f"🔥 AI Sports Picks — {today_str} ({len(daily_picks)} picks, {len(smart_sets)} sets)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.email_from
    msg["To"]      = to_addr

    html_body = _build_html(daily_picks, smart_sets)
    msg.attach(MIMEText(html_body, "html"))

    try:
        port = settings.email_smtp_port
        host = settings.email_smtp_host

        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()

        if settings.email_smtp_user and settings.email_smtp_pass:
            server.login(settings.email_smtp_user, settings.email_smtp_pass)

        server.sendmail(settings.email_from, to_addr, msg.as_string())
        server.quit()
        logger.info(f"Daily email sent to {to_addr}")
        return True

    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False
