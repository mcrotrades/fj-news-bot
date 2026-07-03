"""
═══════════════════════════════════════════════════════════════
  FJ NEWS BOT — Financial Juice Flash + Economic Data Results
  Broadcasts to Telegram: Circle of Traders & MCROTRADES
  Author: RD | Version: 1.0
═══════════════════════════════════════════════════════════════
"""

import feedparser
import requests
import time
import json
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Thread
import xml.etree.ElementTree as ET

# ─── CONFIG ────────────────────────────────────────────────────────────────────
from config import (
    BOT_TOKEN,
    CHANNEL_COT,       # Circle of Traders channel ID
    CHANNEL_MCR,       # MCROTRADES channel ID
    FJ_POLL_INTERVAL,  # seconds between FJ RSS checks (default 90)
    ECON_POLL_INTERVAL # seconds between econ calendar checks (default 120)
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

# ─── CONSTANTS ─────────────────────────────────────────────────────────────────

FJ_FEEDS = {
    "forex":    "https://www.financialjuice.com/feed.aspx?xy=rss&category=forex",
    "macro":    "https://www.financialjuice.com/feed.aspx?xy=rss&category=macro",
    "market":   "https://www.financialjuice.com/feed.aspx?xy=rss&category=marketmoving",
    "all":      "https://www.financialjuice.com/feed.aspx?xy=rss",
}

# ForexFactory calendar endpoint (JSON)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Backup: investing.com econ calendar (scraped via public endpoint)
INVESTING_URL = "https://www.investing.com/economic-calendar/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Referer": "https://www.financialjuice.com/",
}

# High-impact currency keywords for filtering
CURRENCY_KEYWORDS = {
    "USD": ["fed", "fomc", "powell", "nfp", "cpi", "ppi", "gdp", "retail sales",
            "unemployment", "jobless", "ism", "pce", "durable goods", "jolts",
            "dollar", "usd", "us ", "u.s.", "american", "treasury", "yellen"],
    "EUR": ["ecb", "lagarde", "euro", "eur", "eurozone", "german", "france",
            "italy", "spain", "inflation eu", "ifo", "zew"],
    "GBP": ["boe", "bailey", "sterling", "pound", "gbp", "uk ", "britain",
            "british", "england", "gilts"],
    "JPY": ["boj", "ueda", "yen", "jpy", "japan", "japanese", "tankan"],
    "AUD": ["rba", "bullock", "aud", "australia", "aussie"],
    "NZD": ["rbnz", "orr", "nzd", "new zealand", "kiwi"],
    "CAD": ["boc", "macklem", "cad", "canada", "canadian", "loonie", "oil"],
    "CHF": ["snb", "jordan", "chf", "swiss", "switzerland"],
    "GOLD": ["gold", "xau", "xauusd", "bullion"],
    "OIL":  ["crude", "wti", "brent", "opec", "oil"],
}

# High-impact economic event keywords
HIGH_IMPACT_EVENTS = [
    "nfp", "non-farm", "non farm", "fomc", "fed rate", "cpi", "ppi",
    "gdp", "unemployment rate", "jobless claims", "retail sales",
    "interest rate", "rate decision", "payroll", "inflation", "pce",
    "ism manufacturing", "ism services", "jolts", "building permits",
    "trade balance", "current account", "boe", "ecb", "boj", "rba",
    "rbnz", "boc", "snb", "central bank"
]

# Impact level emojis
IMPACT_EMOJI = {
    "high":   "🔴",
    "medium": "🟡",
    "low":    "⚪",
    "news":   "📰",
}

# ─── STATE TRACKERS ────────────────────────────────────────────────────────────

seen_fj_guids     = set()   # Already-sent FJ news IDs
seen_econ_events  = set()   # Already-sent econ event IDs (event_id + date)
econ_results_sent = set()   # Events where actual result was already broadcast

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def pht_now():
    return datetime.now(PHT)

def pht_str(dt=None):
    t = dt or pht_now()
    return t.strftime("%H:%M PHT")

def detect_currencies(text: str) -> list:
    text_lower = text.lower()
    found = []
    for ccy, keywords in CURRENCY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(ccy)
    return found[:4]  # cap at 4

def detect_impact(title: str, tags: list = None) -> str:
    title_lower = title.lower()
    tag_str = " ".join(tags or []).lower()
    combined = title_lower + " " + tag_str
    if any(kw in combined for kw in HIGH_IMPACT_EVENTS):
        return "high"
    if any(c in combined for c in ["rate", "inflation", "gdp", "employment", "bank"]):
        return "medium"
    return "low"

def send_telegram(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        else:
            log.warning(f"Telegram error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False

def broadcast(text: str):
    """Send to both channels."""
    ok1 = send_telegram(CHANNEL_COT, text)
    ok2 = send_telegram(CHANNEL_MCR, text)
    if ok1 or ok2:
        log.info(f"Broadcast sent | COT={ok1} MCR={ok2}")
    time.sleep(0.5)  # Telegram rate limit buffer

# ─── MESSAGE FORMATTERS ────────────────────────────────────────────────────────

def format_fj_flash(title: str, category: str, url: str, impact: str,
                    currencies: list, pub_time: str) -> str:
    """Format a Financial Juice news flash message."""
    impact_e = IMPACT_EMOJI.get(impact, "⚪")
    cat_upper = category.upper()

    # Currency flags
    FLAG_MAP = {
        "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
        "AUD": "🇦🇺", "NZD": "🇳🇿", "CAD": "🇨🇦", "CHF": "🇨🇭",
        "GOLD": "🥇", "OIL": "🛢️",
    }
    flag_str = " ".join(FLAG_MAP.get(c, "") for c in currencies if c in FLAG_MAP)
    ccy_line  = f"\n💱 <b>Affects:</b> {flag_str} {' | '.join(currencies)}" if currencies else ""

    msg = (
        f"📰 <b>FINANCIAL JUICE FLASH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>{pub_time}</b>  {impact_e} <code>{cat_upper}</code>\n\n"
        f"<b>{title}</b>"
        f"{ccy_line}\n\n"
        f"🔗 <a href='{url}'>Read more</a>"
    )
    return msg

def format_econ_result(event: dict) -> str:
    """
    Format an economic data result.
    event keys: title, country, currency, date, time, impact,
                actual, forecast, previous
    """
    FLAG_MAP = {
        "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
        "AUD": "🇦🇺", "NZD": "🇳🇿", "CAD": "🇨🇦", "CHF": "🇨🇭",
    }
    impact_map = {"High": "🔴 HIGH", "Medium": "🟡 MEDIUM", "Low": "⚪ LOW"}

    currency = event.get("currency", "")
    flag     = FLAG_MAP.get(currency, "🌐")
    impact   = impact_map.get(event.get("impact", ""), "⚪")
    title    = event.get("title", "Unknown Event")
    actual   = event.get("actual", "—")
    forecast = event.get("forecast", "—")
    previous = event.get("previous", "—")
    evt_time = event.get("time", "")

    # Beat / miss / inline
    beat_miss = ""
    try:
        act_val  = float(re.sub(r"[^0-9.\-]", "", actual))
        fore_val = float(re.sub(r"[^0-9.\-]", "", forecast))
        if act_val > fore_val:
            beat_miss = "  ✅ <b>BEAT</b>"
        elif act_val < fore_val:
            beat_miss = "  ❌ <b>MISS</b>"
        else:
            beat_miss = "  ➖ <b>IN-LINE</b>"
    except Exception:
        pass

    # Currency impact direction hint
    impact_hint = _currency_impact_hint(currency, title, beat_miss)

    msg = (
        f"📊 <b>ECONOMIC DATA RESULT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{flag} <b>{currency}</b> | {impact}\n"
        f"🕐 <b>{evt_time} PHT</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"<code>"
        f"Actual:   {actual:>10}{beat_miss.replace('<b>','').replace('</b>','').replace('✅','✅').replace('❌','❌').replace('➖','➖') if actual != '—' else ''}\n"
        f"Forecast: {forecast:>10}\n"
        f"Previous: {previous:>10}"
        f"</code>"
        f"{impact_hint}"
    )
    return msg

def _currency_impact_hint(currency: str, title: str, beat_miss: str) -> str:
    """Generate a simple directional bias hint based on result."""
    if not beat_miss or "—" in beat_miss:
        return ""
    title_lower = title.lower()
    is_beat = "BEAT" in beat_miss
    is_miss = "MISS" in beat_miss

    # Inversion logic: some data is inverted (e.g. unemployment = lower is better)
    inverted = any(w in title_lower for w in [
        "unemployment", "jobless", "claims", "deficit", "inflation" # inflation beat = bearish for bonds
    ])

    if inverted:
        bullish = is_miss
    else:
        bullish = is_beat

    if bullish:
        return f"\n\n💹 <b>{currency} BULLISH</b> — Expect strength"
    else:
        return f"\n\n📉 <b>{currency} BEARISH</b> — Expect weakness"

# ─── FINANCIAL JUICE RSS POLLER ────────────────────────────────────────────────

def fetch_fj_news(feed_url: str, category: str) -> list:
    """Fetch and parse a Financial Juice RSS feed. Returns list of new items."""
    try:
        r = requests.get(feed_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning(f"FJ RSS [{category}] HTTP {r.status_code}")
            return []
        feed = feedparser.parse(r.content)
        items = []
        for entry in feed.entries:
            guid = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not guid or guid in seen_fj_guids:
                continue
            title = entry.get("title", "").strip()
            url   = entry.get("link", "https://www.financialjuice.com")
            tags  = [t.get("term", "") for t in entry.get("tags", [])]
            pub   = entry.get("published", "")
            items.append({
                "guid":     guid,
                "title":    title,
                "url":      url,
                "tags":     tags,
                "pub":      pub,
                "category": category,
            })
        return items
    except Exception as e:
        log.error(f"FJ RSS fetch error [{category}]: {e}")
        return []

def fj_news_loop():
    """Main loop: poll FJ RSS feeds and broadcast new items."""
    log.info("▶ Financial Juice news watcher started")
    # Initial load — populate seen GUIDs without broadcasting (avoid flood on startup)
    log.info("  Loading existing GUIDs (suppressing startup flood)...")
    for category, url in FJ_FEEDS.items():
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                guid = entry.get("id") or entry.get("link") or entry.get("title", "")
                if guid:
                    seen_fj_guids.add(guid)
    log.info(f"  Seeded {len(seen_fj_guids)} existing GUIDs. Live monitoring starts now.")

    while True:
        try:
            for category, url in FJ_FEEDS.items():
                new_items = fetch_fj_news(url, category)
                if not new_items:
                    continue

                # Deduplicate across categories (same story may appear in multiple feeds)
                unique_items = [i for i in new_items if i["guid"] not in seen_fj_guids]

                for item in unique_items:
                    seen_fj_guids.add(item["guid"])
                    impact     = detect_impact(item["title"], item["tags"])
                    currencies = detect_currencies(item["title"])
                    pub_time   = pht_str()  # Use current PHT time since FJ pub times are UTC

                    msg = format_fj_flash(
                        title=item["title"],
                        category=item["category"],
                        url=item["url"],
                        impact=impact,
                        currencies=currencies,
                        pub_time=pub_time,
                    )
                    log.info(f"[FJ] NEW: {item['title'][:80]}")
                    broadcast(msg)
                    time.sleep(1)  # stagger multi-item bursts

        except Exception as e:
            log.error(f"fj_news_loop error: {e}")

        time.sleep(FJ_POLL_INTERVAL)

# ─── ECONOMIC CALENDAR POLLER ──────────────────────────────────────────────────

def fetch_ff_calendar() -> list:
    """
    Fetch ForexFactory economic calendar (JSON endpoint).
    Returns list of events for today in PHT.
    """
    try:
        r = requests.get(
            FF_CALENDAR_URL,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15
        )
        if r.status_code != 200:
            log.warning(f"FF Calendar HTTP {r.status_code}")
            return []
        events = r.json()
        today_utc = datetime.utcnow().strftime("%m-%d-%Y")
        # Filter today + tomorrow (to catch overnight events)
        tomorrow_utc = (datetime.utcnow() + timedelta(days=1)).strftime("%m-%d-%Y")
        filtered = [
            e for e in events
            if e.get("date", "") in [today_utc, tomorrow_utc]
            and e.get("impact", "Low") in ["High", "Medium"]
        ]
        return filtered
    except Exception as e:
        log.error(f"FF Calendar fetch error: {e}")
        return []

def utc_to_pht(date_str: str, time_str: str) -> str:
    """
    Convert ForexFactory UTC date+time to PHT string.
    date_str: "05-29-2026"  time_str: "8:30am"
    """
    try:
        combined = f"{date_str} {time_str}"
        dt_utc = datetime.strptime(combined, "%m-%d-%Y %I:%M%p")
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        dt_pht = dt_utc.astimezone(PHT)
        return dt_pht.strftime("%H:%M PHT (%d %b)")
    except Exception:
        return time_str or "TBA"

def make_event_key(event: dict) -> str:
    return f"{event.get('title','')}_{event.get('date','')}_{event.get('time','')}"

def econ_calendar_loop():
    """
    Main loop:
    1. Pre-broadcast upcoming high-impact events (30 min warning)
    2. Detect and broadcast actual results when they post
    """
    log.info("▶ Economic calendar watcher started")

    while True:
        try:
            events = fetch_ff_calendar()
            now_utc = datetime.utcnow()

            for evt in events:
                key    = make_event_key(evt)
                impact = evt.get("impact", "Low")
                actual = evt.get("actual", "")

                # ── Result broadcast (when actual data is posted) ──
                if actual and key not in econ_results_sent:
                    econ_results_sent.add(key)
                    # Build PHT time string
                    evt_time = utc_to_pht(evt.get("date",""), evt.get("time",""))
                    msg = format_econ_result({
                        "title":    evt.get("title", "Economic Release"),
                        "country":  evt.get("country", ""),
                        "currency": evt.get("currency", ""),
                        "date":     evt.get("date", ""),
                        "time":     evt_time,
                        "impact":   impact,
                        "actual":   actual,
                        "forecast": evt.get("forecast", "—"),
                        "previous": evt.get("previous", "—"),
                    })
                    log.info(f"[ECON RESULT] {evt.get('title')} | Actual={actual}")
                    broadcast(msg)
                    continue

                # ── Upcoming event warning (30 min before) ──
                if key in seen_econ_events:
                    continue

                try:
                    combined = f"{evt.get('date','')} {evt.get('time','')}"
                    evt_dt_utc = datetime.strptime(combined, "%m-%d-%Y %I:%M%p")
                    minutes_until = (evt_dt_utc - now_utc).total_seconds() / 60
                except Exception:
                    continue

                if 25 <= minutes_until <= 35 and impact == "High":
                    seen_econ_events.add(key)
                    evt_pht = utc_to_pht(evt.get("date",""), evt.get("time",""))
                    flag_map = {
                        "USD":"🇺🇸","EUR":"🇪🇺","GBP":"🇬🇧","JPY":"🇯🇵",
                        "AUD":"🇦🇺","NZD":"🇳🇿","CAD":"🇨🇦","CHF":"🇨🇭",
                    }
                    ccy  = evt.get("currency","")
                    flag = flag_map.get(ccy, "🌐")
                    msg = (
                        f"⏰ <b>UPCOMING HIGH-IMPACT EVENT</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{flag} <b>{ccy}</b> | 🔴 HIGH IMPACT\n"
                        f"⚡ <b>In ~30 minutes</b> — {evt_pht}\n\n"
                        f"<b>{evt.get('title','')}</b>\n\n"
                        f"<code>"
                        f"Forecast: {evt.get('forecast','—'):>10}\n"
                        f"Previous: {evt.get('previous','—'):>10}"
                        f"</code>\n\n"
                        f"⚠️ Expect volatility — manage risk!"
                    )
                    log.info(f"[ECON WARN] {evt.get('title')} in ~30min")
                    broadcast(msg)

        except Exception as e:
            log.error(f"econ_calendar_loop error: {e}")

        time.sleep(ECON_POLL_INTERVAL)

# ─── STARTUP BANNER ────────────────────────────────────────────────────────────

def send_startup_banner():
    now = pht_now()
    msg = (
        f"🚀 <b>FJ NEWS BOT ONLINE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Started: <b>{now.strftime('%Y-%m-%d %H:%M PHT')}</b>\n\n"
        f"📡 Monitoring:\n"
        f"  • Financial Juice RSS (Forex · Macro · Market Moving)\n"
        f"  • ForexFactory Economic Calendar\n\n"
        f"🔔 You'll receive:\n"
        f"  1. Live news flashes as they break\n"
        f"  2. ⚠️ 30-min warnings for high-impact events\n"
        f"  3. 📊 Actual vs Forecast results on release\n\n"
        f"📢 Broadcasting to: Circle of Traders + MCROTRADES"
    )
    broadcast(msg)

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("═" * 60)
    log.info("  FJ NEWS BOT v1.0  |  Starting up...")
    log.info("═" * 60)

    # MAX_RUNTIME_MINUTES: set via env var or default to 270 min (4.5 hours)
    # GitHub Actions kills jobs at 6 hours — we exit cleanly at 4.5h
    # The workflow cron restarts us every 5 hours, so there's a ~30min overlap buffer
    MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", 270))
    start_time = time.time()
    deadline   = start_time + (MAX_RUNTIME_MINUTES * 60)

    log.info(f"  Runtime limit: {MAX_RUNTIME_MINUTES} min (exits cleanly before GitHub kills us)")

    send_startup_banner()

    # Run both loops in separate daemon threads
    t1 = Thread(target=fj_news_loop,        daemon=True, name="FJ-RSS")
    t2 = Thread(target=econ_calendar_loop,  daemon=True, name="ECON-CAL")
    t1.start()
    t2.start()

    log.info("Both watchers running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            if time.time() >= deadline:
                log.info(f"⏰ Runtime limit reached ({MAX_RUNTIME_MINUTES} min). Exiting cleanly — cron will restart.")
                break
    except KeyboardInterrupt:
        log.info("Shutdown requested. Bye!")
