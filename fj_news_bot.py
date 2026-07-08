"""
═══════════════════════════════════════════════════════════════
  FJ NEWS BOT v3.0 — News Flash + AI Trading Analysis
  Broadcasts to Telegram channels
  Author: RD | Version: 3.0
  - Multi-source RSS with automatic fallback
  - Claude AI analysis on every news item
  - SMC context, currency impact, Gold/Oil implications
═══════════════════════════════════════════════════════════════
"""

import feedparser
import requests
import time
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Thread

# ─── CONFIG ────────────────────────────────────────────────────────────────────
from config import (
    BOT_TOKEN,
    CHANNEL_COT,
    CHANNEL_MCR,
    FJ_POLL_INTERVAL,
    ECON_POLL_INTERVAL,
    GROQ_API_KEY,
    GEMINI_API_KEY,
)

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("fj_news_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("FJ_BOT")

PHT = ZoneInfo("Asia/Manila")

# ─── NEWS SOURCES ──────────────────────────────────────────────────────────────
NEWS_SOURCES = [
    {"name": "FinancialJuice", "url": "https://www.financialjuice.com/feed.aspx?xy=rss",  "label": "FJ"},
    {"name": "ForexLive",      "url": "https://www.forexlive.com/feed/news",               "label": "ForexLive"},
    {"name": "FXStreet",       "url": "https://www.fxstreet.com/rss/news",                 "label": "FXStreet"},
    {"name": "DailyFX",        "url": "https://www.dailyfx.com/feeds/all",                 "label": "DailyFX"},
    {"name": "Investing",      "url": "https://www.investing.com/rss/news.rss",            "label": "Investing"},
]

CALENDAR_SOURCES = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ─── KEYWORD MAPS ──────────────────────────────────────────────────────────────
CURRENCY_KEYWORDS = {
    "USD":  ["fed", "fomc", "powell", "nfp", "cpi", "ppi", "gdp", "retail sales",
             "unemployment", "jobless", "ism", "pce", "durable goods", "jolts",
             "dollar", "usd", "us ", "u.s.", "american", "treasury"],
    "EUR":  ["ecb", "lagarde", "euro", "eur", "eurozone", "german", "france",
             "italy", "spain", "ifo", "zew"],
    "GBP":  ["boe", "bailey", "sterling", "pound", "gbp", "uk ", "britain", "british"],
    "JPY":  ["boj", "ueda", "yen", "jpy", "japan", "japanese", "tankan"],
    "AUD":  ["rba", "bullock", "aud", "australia", "aussie"],
    "NZD":  ["rbnz", "orr", "nzd", "new zealand", "kiwi"],
    "CAD":  ["boc", "macklem", "cad", "canada", "canadian", "loonie"],
    "CHF":  ["snb", "jordan", "chf", "swiss", "switzerland"],
    "GOLD": ["gold", "xau", "xauusd", "bullion"],
    "OIL":  ["crude", "wti", "brent", "opec", "oil"],
}

HIGH_IMPACT_EVENTS = [
    "nfp", "non-farm", "non farm", "fomc", "fed rate", "cpi", "ppi",
    "gdp", "unemployment rate", "jobless claims", "retail sales",
    "interest rate", "rate decision", "payroll", "inflation", "pce",
    "ism manufacturing", "ism services", "jolts", "building permits",
    "trade balance", "current account", "boe", "ecb", "boj", "rba",
    "rbnz", "boc", "snb", "central bank",
]

FLAG_MAP = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
    "AUD": "🇦🇺", "NZD": "🇳🇿", "CAD": "🇨🇦", "CHF": "🇨🇭",
    "GOLD": "🥇", "OIL": "🛢️",
}

# ─── STATE ─────────────────────────────────────────────────────────────────────
seen_guids        = set()
seen_econ_events  = set()
econ_results_sent = set()
active_source     = None

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def pht_now():
    return datetime.now(PHT)

def pht_str(dt=None):
    return (dt or pht_now()).strftime("%H:%M PHT")

def detect_currencies(text: str) -> list:
    text_lower = text.lower()
    return [c for c, kws in CURRENCY_KEYWORDS.items() if any(k in text_lower for k in kws)][:4]

def detect_impact(title: str, tags: list = None) -> str:
    combined = (title + " " + " ".join(tags or [])).lower()
    if any(kw in combined for kw in HIGH_IMPACT_EVENTS):
        return "high"
    if any(w in combined for w in ["rate", "inflation", "gdp", "employment", "bank"]):
        return "medium"
    return "low"

def send_telegram(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code == 200:
            return True
        log.warning(f"Telegram error {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False

def broadcast(text: str):
    ok1 = send_telegram(CHANNEL_COT, text)
    ok2 = send_telegram(CHANNEL_MCR, text)
    log.info(f"Broadcast | COT={ok1} MCR={ok2}")
    time.sleep(0.5)

# ─── AI ANALYSIS (Gemini primary, Groq fallback) ──────────────────────────────
AI_SYSTEM_PROMPT = """You are an elite forex and commodities trader with deep expertise in:
- Smart Money Concepts (SMC): Order Blocks, FVGs, IFVGs, Liquidity sweeps, CISD
- Multi-timeframe analysis (HTF bias → LTF entry)
- Macro and fundamental analysis
- Cross-asset correlations (DXY, Gold, Oil, Risk-on/off)

When given a market news headline, respond with a concise trading analysis in this EXACT format:

📌 BIAS: [1 sentence — what this means for the market]
💱 IMPACT:
• [Currency/Asset]: [Bullish/Bearish/Neutral] — [reason]
• [Currency/Asset]: [Bullish/Bearish/Neutral] — [reason]
🎯 WATCH: [1-2 key levels or setups to watch]
⚠️ RISK: [any tail risk or caveat]

Keep it short, sharp, and actionable. Max 5 lines total. No fluff."""

def call_gemini(prompt: str) -> str:
    """Call Google Gemini API (free). Returns analysis or empty string."""
    if not GEMINI_API_KEY:
        return ""
    try:
        # Try both model versions for compatibility
        models = ["gemini-1.5-flash", "gemini-pro", "gemini-1.0-pro"]
        full_prompt = AI_SYSTEM_PROMPT + "\n\n" + prompt
        for model in models:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            r = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{"text": full_prompt}]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": 300,
                        "temperature": 0.3,
                    }
                },
                timeout=20,
            )
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                log.info(f"[AI/Gemini] Analysis done via {model}")
                return text
            elif r.status_code == 404:
                log.debug(f"[AI/Gemini] Model {model} not found, trying next...")
                continue
            else:
                log.warning(f"[AI/Gemini] Error {r.status_code}: {r.text[:150]}")
                break
        return ""
    except Exception as e:
        log.error(f"[AI/Gemini] Failed: {e}")
        return ""

def call_groq(prompt: str) -> str:
    """Call Groq API (free fallback). Returns analysis or empty string."""
    if not GROQ_API_KEY:
        log.warning("[AI/Groq] No API key found!")
        return ""
    log.info(f"[AI/Groq] Calling API, key starts with: {GROQ_API_KEY[:8]}...")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 300,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            },
            timeout=20,
        )
        log.info(f"[AI/Groq] Response status: {r.status_code}")
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"]["content"].strip()
            log.info("[AI/Groq] Analysis done ✅")
            return text
        log.warning(f"[AI/Groq] Error {r.status_code}: {r.text[:200]}")
        return ""
    except Exception as e:
        log.error(f"[AI/Groq] Failed: {e}")
        return ""

def call_ai(prompt: str) -> str:
    """Try Gemini first, fall back to Groq."""
    result = call_gemini(prompt)
    if result:
        return result
    return call_groq(prompt)

def get_ai_analysis(headline: str) -> str:
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        return ""
    return call_ai(f"Analyze this market news for trading: {headline}")

def get_ai_econ_analysis(title: str, currency: str, actual: str,
                          forecast: str, previous: str, beat_miss: str) -> str:
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        return ""
    prompt = (
        f"Economic data released:\n"
        f"Event: {title}\n"
        f"Currency: {currency}\n"
        f"Actual: {actual} ({beat_miss})\n"
        f"Forecast: {forecast}\n"
        f"Previous: {previous}\n\n"
        f"Give a concise SMC trading analysis."
    )
    return call_ai(prompt)

# ─── MESSAGE FORMATTERS ────────────────────────────────────────────────────────
def format_news_flash(title, source_label, url, impact, currencies, ai_analysis="") -> str:
    impact_e = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(impact, "⚪")
    flag_str = " ".join(FLAG_MAP.get(c, "") for c in currencies if c in FLAG_MAP)
    ccy_line = f"\n💱 <b>Affects:</b> {flag_str} {' | '.join(currencies)}" if currencies else ""
    ai_block = f"\n\n🤖 <b>AI ANALYSIS:</b>\n{ai_analysis}" if ai_analysis else ""
    return (
        f"📰 <b>MARKET NEWS FLASH</b>  <code>[{source_label}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>{pht_str()}</b>  {impact_e}\n\n"
        f"<b>{title}</b>"
        f"{ccy_line}"
        f"{ai_block}\n\n"
        f"🔗 <a href='{url}'>Read more</a>"
    )

def format_econ_result(event: dict, ai_analysis: str = "") -> str:
    impact_map = {"High": "🔴 HIGH", "Medium": "🟡 MEDIUM", "Low": "⚪ LOW"}
    currency = event.get("currency", "")
    flag     = FLAG_MAP.get(currency, "🌐")
    impact   = impact_map.get(event.get("impact", ""), "⚪")
    actual   = event.get("actual", "—")
    forecast = event.get("forecast", "—")
    previous = event.get("previous", "—")

    beat_miss = ""
    hint = ""
    try:
        av = float(re.sub(r"[^0-9.\-]", "", actual))
        fv = float(re.sub(r"[^0-9.\-]", "", forecast))
        inverted = any(w in event.get("title","").lower()
                       for w in ["unemployment", "jobless", "claims", "deficit"])
        if av > fv:
            beat_miss = "✅ BEAT"
            hint = f"\n\n💹 <b>{currency} BULLISH</b>" if not inverted else f"\n\n📉 <b>{currency} BEARISH</b>"
        elif av < fv:
            beat_miss = "❌ MISS"
            hint = f"\n\n📉 <b>{currency} BEARISH</b>" if not inverted else f"\n\n💹 <b>{currency} BULLISH</b>"
        else:
            beat_miss = "➖ IN-LINE"
    except Exception:
        pass

    ai_block = f"\n\n🤖 <b>AI ANALYSIS:</b>\n{ai_analysis}" if ai_analysis else hint

    return (
        f"📊 <b>ECONOMIC DATA RESULT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{flag} <b>{currency}</b> | {impact}\n"
        f"🕐 <b>{event.get('time', '')} PHT</b>\n\n"
        f"<b>{event.get('title', '')}</b>\n\n"
        f"<code>"
        f"Actual:   {actual:>10}  {beat_miss}\n"
        f"Forecast: {forecast:>10}\n"
        f"Previous: {previous:>10}"
        f"</code>"
        f"{ai_block}"
    )

def format_econ_warning(evt: dict, evt_pht: str) -> str:
    currency = evt.get("currency", "")
    flag     = FLAG_MAP.get(currency, "🌐")
    return (
        f"⏰ <b>UPCOMING HIGH-IMPACT EVENT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{flag} <b>{currency}</b> | 🔴 HIGH IMPACT\n"
        f"⚡ <b>In ~30 minutes</b> — {evt_pht}\n\n"
        f"<b>{evt.get('title', '')}</b>\n\n"
        f"<code>"
        f"Forecast: {evt.get('forecast', '—'):>10}\n"
        f"Previous: {evt.get('previous', '—'):>10}"
        f"</code>\n\n"
        f"⚠️ Expect volatility — manage your risk!"
    )

# ─── RSS FETCHER ───────────────────────────────────────────────────────────────
def fetch_rss(source: dict) -> list:
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        feed = feedparser.parse(r.content)
        if not feed.entries:
            return []
        items = []
        for entry in feed.entries:
            guid  = entry.get("id") or entry.get("link") or entry.get("title", "")
            title = entry.get("title", "").strip()
            url   = entry.get("link", source["url"])
            tags  = [t.get("term", "") for t in entry.get("tags", [])]
            if not guid or not title:
                continue
            items.append({
                "guid":   guid,
                "title":  title,
                "url":    url,
                "tags":   tags,
                "source": source["name"],
                "label":  source["label"],
            })
        return items
    except Exception as e:
        log.debug(f"RSS fetch error [{source['name']}]: {e}")
        return []

def seed_existing_guids():
    """
    Seed old GUIDs to prevent flood — but keep the latest 5 headlines
    UNSEEN so they get broadcast immediately on startup.
    This ensures the channel always gets fresh news on bot start.
    """
    log.info("  Seeding existing GUIDs (keeping latest 5 fresh)...")
    for source in NEWS_SOURCES:
        items = fetch_rss(source)
        if not items:
            continue
        # Seed all EXCEPT the 5 most recent ones
        to_seed = items[5:]  # skip first 5 (newest), seed the rest
        for item in to_seed:
            seen_guids.add(item["guid"])
        log.info(f"  [{source['name']}] seeded {len(to_seed)} old GUIDs, keeping {min(5,len(items))} fresh")
        break  # Only need to seed from first working source
    log.info(f"  Total seeded: {len(seen_guids)} GUIDs. Latest headlines will broadcast now.")

# ─── NEWS LOOP ─────────────────────────────────────────────────────────────────
def news_loop():
    global active_source
    log.info("▶ News watcher started (multi-source with fallback + AI analysis)")
    seed_existing_guids()

    while True:
        try:
            found_any = False
            for source in NEWS_SOURCES:
                items = fetch_rss(source)
                if not items:
                    continue

                if active_source != source["name"]:
                    log.info(f"  ✅ Active source switched to: {source['name']}")
                    active_source = source["name"]

                new_items = [i for i in items if i["guid"] not in seen_guids]
                for item in new_items:
                    seen_guids.add(item["guid"])
                    impact     = detect_impact(item["title"], item["tags"])
                    currencies = detect_currencies(item["title"])

                    # Call AI for all news
                    ai_analysis = get_ai_analysis(item["title"])

                    msg = format_news_flash(
                        title=item["title"],
                        source_label=item["label"],
                        url=item["url"],
                        impact=impact,
                        currencies=currencies,
                        ai_analysis=ai_analysis,
                    )
                    log.info(f"[{item['label']}] NEW: {item['title'][:80]}")
                    broadcast(msg)
                    time.sleep(1)

                found_any = True
                break

            if not found_any:
                log.warning("⚠️ All RSS sources unavailable this cycle — will retry")

        except Exception as e:
            log.error(f"news_loop error: {e}")

        time.sleep(FJ_POLL_INTERVAL)

# ─── ECONOMIC CALENDAR LOOP ────────────────────────────────────────────────────
# Track consecutive calendar failures to apply backoff
_calendar_fail_count = 0

def fetch_calendar() -> list:
    global _calendar_fail_count

    # TradingEconomics guest key — free, no signup needed
    te_url = "https://api.tradingeconomics.com/calendar?c=guest:guest&f=json"

    all_sources = CALENDAR_SOURCES + [te_url]

    for url in all_sources:
        try:
            r = requests.get(
                url,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    _calendar_fail_count = 0
                    log.debug(f"Calendar OK from {url} — {len(data)} events")
                    # Normalize TradingEconomics format if needed
                    if "tradingeconomics" in url:
                        return _normalize_te_calendar(data)
                    return data
            elif r.status_code == 429:
                log.warning(f"Calendar rate-limited (429) from {url} — trying next source")
            else:
                log.warning(f"Calendar HTTP {r.status_code} from {url}")
        except Exception as e:
            log.debug(f"Calendar error [{url}]: {e}")

    _calendar_fail_count += 1
    if _calendar_fail_count <= 3:
        log.warning(f"⚠️ All calendar sources unavailable (attempt {_calendar_fail_count})")
    return []

def _normalize_te_calendar(data: list) -> list:
    """Convert TradingEconomics format to ForexFactory-compatible format."""
    result = []
    for evt in data:
        try:
            # TE date format: "2026-07-04T08:30:00"
            dt_str = evt.get("Date", "")
            dt = datetime.fromisoformat(dt_str.replace("Z",""))
            date_fmt = dt.strftime("%m-%d-%Y")
            time_fmt = dt.strftime("%I:%M%p").lstrip("0")
            importance = evt.get("Importance", 1)
            impact = "High" if importance == 3 else ("Medium" if importance == 2 else "Low")
            result.append({
                "title":    evt.get("Event", ""),
                "country":  evt.get("Country", ""),
                "currency": evt.get("Currency", "").upper(),
                "date":     date_fmt,
                "time":     time_fmt,
                "impact":   impact,
                "actual":   str(evt.get("Actual", "")) if evt.get("Actual") is not None else "",
                "forecast": str(evt.get("Forecast", "")) if evt.get("Forecast") is not None else "—",
                "previous": str(evt.get("Previous", "")) if evt.get("Previous") is not None else "—",
            })
        except Exception:
            continue
    return result

def utc_to_pht(date_str: str, time_str: str) -> str:
    try:
        dt_utc = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(PHT).strftime("%H:%M PHT (%d %b)")
    except Exception:
        return time_str or "TBA"

def make_event_key(evt: dict) -> str:
    return f"{evt.get('title','')}_{evt.get('date','')}_{evt.get('time','')}"

def econ_loop():
    log.info("▶ Economic calendar watcher started")
    while True:
        try:
            events = fetch_calendar()
            now_utc = datetime.utcnow()

            for evt in events:
                key    = make_event_key(evt)
                impact = evt.get("impact", "Low")
                actual = evt.get("actual", "")

                # ── Result broadcast ──
                if actual and key not in econ_results_sent:
                    econ_results_sent.add(key)
                    evt_pht  = utc_to_pht(evt.get("date", ""), evt.get("time", ""))
                    forecast = evt.get("forecast", "—")
                    previous = evt.get("previous", "—")
                    currency = evt.get("currency", "")

                    # Determine beat/miss for AI prompt
                    beat_miss = ""
                    try:
                        av = float(re.sub(r"[^0-9.\-]", "", actual))
                        fv = float(re.sub(r"[^0-9.\-]", "", forecast))
                        beat_miss = "BEAT" if av > fv else ("MISS" if av < fv else "IN-LINE")
                    except Exception:
                        pass

                    ai_analysis = get_ai_econ_analysis(
                        title=evt.get("title", ""),
                        currency=currency,
                        actual=actual,
                        forecast=forecast,
                        previous=previous,
                        beat_miss=beat_miss,
                    )

                    msg = format_econ_result({**evt, "time": evt_pht}, ai_analysis)
                    log.info(f"[ECON RESULT] {evt.get('title')} | Actual={actual}")
                    broadcast(msg)
                    continue

                # ── 30-min warning ──
                if key in seen_econ_events or impact != "High":
                    continue
                try:
                    evt_dt = datetime.strptime(
                        f"{evt.get('date','')} {evt.get('time','')}",
                        "%m-%d-%Y %I:%M%p"
                    )
                    mins_until = (evt_dt - now_utc).total_seconds() / 60
                except Exception:
                    continue

                if 25 <= mins_until <= 35:
                    seen_econ_events.add(key)
                    evt_pht = utc_to_pht(evt.get("date", ""), evt.get("time", ""))
                    msg = format_econ_warning(evt, evt_pht)
                    log.info(f"[ECON WARN] {evt.get('title')} in ~30min")
                    broadcast(msg)

        except Exception as e:
            log.error(f"econ_loop error: {e}")

        time.sleep(ECON_POLL_INTERVAL)

# ─── STARTUP BANNER ────────────────────────────────────────────────────────────
def send_startup_banner():
    if GROQ_API_KEY:
        ai_status = "✅ Groq/Llama3 (Active)"
    elif GEMINI_API_KEY:
        ai_status = "✅ Google Gemini (Active)"
    else:
        ai_status = "❌ Disabled — add GROQ_API_KEY or GEMINI_API_KEY secret"
    now = pht_now()
    msg = (
        f"🚀 <b>FJ NEWS BOT v3.0 ONLINE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Started: <b>{now.strftime('%Y-%m-%d %H:%M PHT')}</b>\n\n"
        f"📡 <b>News Sources (auto-fallback):</b>\n"
        f"  1. Financial Juice\n"
        f"  2. ForexLive\n"
        f"  3. FXStreet\n"
        f"  4. DailyFX\n\n"
        f"🤖 <b>AI Analysis:</b> {ai_status}\n\n"
        f"📅 <b>Economic Calendar:</b> ForexFactory\n\n"
        f"🔔 <b>You will receive:</b>\n"
        f"  • 📰 Live news + AI trading analysis\n"
        f"  • ⏰ 30-min warnings before high-impact events\n"
        f"  • 📊 Data results with AI bias analysis\n"
        f"  • 📅 Weekly digest every Monday 08:00 PHT"
    )
    broadcast(msg)


# ─── WEEKLY DIGEST ─────────────────────────────────────────────────────────────
weekly_digest_sent = False

def build_weekly_digest() -> str:
    """
    Build a weekly digest using AI summary of last week's major events.
    Pulls from ForexFactory previous week calendar.
    """
    log.info("[DIGEST] Building weekly digest...")

    # Fetch last week's calendar
    lastweek_url = "https://nfs.faireconomy.media/ff_calendar_lastweek.json"
    events = []
    try:
        r = requests.get(lastweek_url, headers={**HEADERS, "Accept": "application/json"}, timeout=15)
        if r.status_code == 200:
            events = r.json()
    except Exception as e:
        log.warning(f"[DIGEST] Could not fetch last week calendar: {e}")

    # Filter only High impact events that have actual data
    high_events = [
        e for e in events
        if e.get("impact") == "High" and e.get("actual")
    ]

    if not high_events:
        log.warning("[DIGEST] No high-impact events found for last week")
        return ""

    # Build summary text for AI
    events_text = ""
    for e in high_events[:15]:  # cap at 15 events
        actual   = e.get("actual", "—")
        forecast = e.get("forecast", "—")
        previous = e.get("previous", "—")
        currency = e.get("currency", "")
        title    = e.get("title", "")
        try:
            av = float(re.sub(r"[^0-9.\-]", "", actual))
            fv = float(re.sub(r"[^0-9.\-]", "", forecast))
            result = "BEAT" if av > fv else ("MISS" if av < fv else "IN-LINE")
        except Exception:
            result = ""
        events_text += f"- {currency} {title}: Actual={actual} Forecast={forecast} Previous={previous} {result}\n"

    # Get AI to summarize
    ai_summary = ""
    if GROQ_API_KEY and events_text:
        try:
            prompt = (
                f"Here are last week's major economic data releases:\n\n"
                f"{events_text}\n"
                f"Write a concise weekly market recap for forex traders. "
                f"Cover: overall market theme, strongest/weakest currencies, "
                f"key surprises, and what to watch this week. "
                f"Format with clear sections. Max 200 words. No fluff."
            )
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "max_tokens": 400,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": "You are an elite forex market analyst writing a weekly recap for traders."},
                        {"role": "user",   "content": prompt},
                    ],
                },
                timeout=25,
            )
            if r.status_code == 200:
                ai_summary = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.error(f"[DIGEST] AI summary failed: {e}")

    # Build the event table
    now_pht = pht_now()
    week_start = (now_pht - timedelta(days=now_pht.weekday() + 7)).strftime("%b %d")
    week_end   = (now_pht - timedelta(days=now_pht.weekday() + 1)).strftime("%b %d")

    lines = []
    for e in high_events[:10]:
        currency = e.get("currency", "")
        title    = e.get("title", "")[:30]
        actual   = e.get("actual", "—")
        forecast = e.get("forecast", "—")
        flag     = FLAG_MAP.get(currency, "🌐")
        try:
            av = float(re.sub(r"[^0-9.\-]", "", actual))
            fv = float(re.sub(r"[^0-9.\-]", "", forecast))
            icon = "✅" if av > fv else ("❌" if av < fv else "➖")
        except Exception:
            icon = "•"
        lines.append(f"{icon} {flag} {title}: <b>{actual}</b> vs {forecast}")

    events_block = "\n".join(lines)
    ai_block = f"\n\n🤖 <b>AI MARKET RECAP:</b>\n{ai_summary}" if ai_summary else ""

    msg = (
        f"📅 <b>WEEKLY MARKET DIGEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗓 Week of <b>{week_start} – {week_end}</b>\n\n"
        f"<b>🔴 HIGH IMPACT RESULTS:</b>\n"
        f"{events_block}"
        f"{ai_block}\n\n"
        f"📊 New week starts now — stay sharp!"
    )
    return msg

def weekly_digest_loop():
    """Posts weekly digest every Monday at 08:00 PHT."""
    global weekly_digest_sent
    log.info("▶ Weekly digest watcher started")
    while True:
        try:
            now = pht_now()
            # Monday = weekday 0, at 08:00 PHT
            is_monday_morning = (now.weekday() == 0 and now.hour == 8 and now.minute < 5)
            if is_monday_morning and not weekly_digest_sent:
                log.info("[DIGEST] Monday 08:00 PHT — sending weekly digest")
                msg = build_weekly_digest()
                if msg:
                    broadcast(msg)
                    weekly_digest_sent = True
                    log.info("[DIGEST] Weekly digest sent!")
            # Reset flag on Tuesday so it can send again next Monday
            if now.weekday() == 1:
                weekly_digest_sent = False
        except Exception as e:
            log.error(f"weekly_digest_loop error: {e}")
        time.sleep(300)  # check every 5 minutes

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═" * 60)
    log.info("  FJ NEWS BOT v3.0  |  Starting up...")
    log.info("═" * 60)

    MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", 270))
    deadline = time.time() + (MAX_RUNTIME_MINUTES * 60)
    log.info(f"  Runtime limit: {MAX_RUNTIME_MINUTES} min")

    send_startup_banner()

    t1 = Thread(target=news_loop,          daemon=True, name="NEWS")
    t2 = Thread(target=econ_loop,          daemon=True, name="ECON")
    t3 = Thread(target=weekly_digest_loop, daemon=True, name="DIGEST")
    t1.start()
    t2.start()
    t3.start()

    log.info("Both watchers running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            if time.time() >= deadline:
                log.info("⏰ Runtime limit reached. Exiting cleanly.")
                break
    except KeyboardInterrupt:
        log.info("Shutdown requested. Bye!")
