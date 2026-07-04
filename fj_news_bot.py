"""
═══════════════════════════════════════════════════════════════
  FJ NEWS BOT v2.0 — Financial Juice Flash + Economic Data
  Broadcasts to Telegram channels
  Author: RD | Version: 2.0
  - Multi-source RSS with automatic fallback
  - ForexFactory + TradingEconomics calendar fallback
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

# ─── NEWS SOURCES (priority order — first working one wins) ────────────────────
NEWS_SOURCES = [
    {
        "name": "FinancialJuice",
        "url":  "https://www.financialjuice.com/feed.aspx?xy=rss",
        "label": "FJ",
    },
    {
        "name": "ForexLive",
        "url":  "https://www.forexlive.com/feed/news",
        "label": "ForexLive",
    },
    {
        "name": "FXStreet",
        "url":  "https://www.fxstreet.com/rss/news",
        "label": "FXStreet",
    },
    {
        "name": "DailyFX",
        "url":  "https://www.dailyfx.com/feeds/all",
        "label": "DailyFX",
    },
    {
        "name": "Investing",
        "url":  "https://www.investing.com/rss/news.rss",
        "label": "Investing",
    },
]

# ─── ECONOMIC CALENDAR SOURCES (priority order) ────────────────────────────────
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
    "USD": ["fed", "fomc", "powell", "nfp", "cpi", "ppi", "gdp", "retail sales",
            "unemployment", "jobless", "ism", "pce", "durable goods", "jolts",
            "dollar", "usd", "us ", "u.s.", "american", "treasury"],
    "EUR": ["ecb", "lagarde", "euro", "eur", "eurozone", "german", "france",
            "italy", "spain", "ifo", "zew"],
    "GBP": ["boe", "bailey", "sterling", "pound", "gbp", "uk ", "britain",
            "british", "england"],
    "JPY": ["boj", "ueda", "yen", "jpy", "japan", "japanese", "tankan"],
    "AUD": ["rba", "bullock", "aud", "australia", "aussie"],
    "NZD": ["rbnz", "orr", "nzd", "new zealand", "kiwi"],
    "CAD": ["boc", "macklem", "cad", "canada", "canadian", "loonie"],
    "CHF": ["snb", "jordan", "chf", "swiss", "switzerland"],
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
active_source     = None   # tracks which news source is currently working

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

# ─── MESSAGE FORMATTERS ────────────────────────────────────────────────────────
def format_news_flash(title, source_label, url, impact, currencies) -> str:
    impact_e = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(impact, "⚪")
    flag_str = " ".join(FLAG_MAP.get(c, "") for c in currencies if c in FLAG_MAP)
    ccy_line = f"\n💱 <b>Affects:</b> {flag_str} {' | '.join(currencies)}" if currencies else ""
    return (
        f"📰 <b>MARKET NEWS FLASH</b>  <code>[{source_label}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>{pht_str()}</b>  {impact_e}\n\n"
        f"<b>{title}</b>"
        f"{ccy_line}\n\n"
        f"🔗 <a href='{url}'>Read more</a>"
    )

def format_econ_result(event: dict) -> str:
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
        title_l = event.get("title", "").lower()
        inverted = any(w in title_l for w in ["unemployment", "jobless", "claims", "deficit"])
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
        f"{hint}"
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

# ─── RSS FETCHER WITH FALLBACK ─────────────────────────────────────────────────
def fetch_rss(source: dict) -> list:
    """Fetch one RSS source. Returns list of new items or empty list."""
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
    """On startup, load existing GUIDs silently to avoid flood."""
    log.info("  Seeding existing GUIDs...")
    for source in NEWS_SOURCES:
        items = fetch_rss(source)
        for item in items:
            seen_guids.add(item["guid"])
        if items:
            log.info(f"  [{source['name']}] seeded {len(items)} GUIDs")
    log.info(f"  Total seeded: {len(seen_guids)} GUIDs. Live monitoring starts now.")

# ─── NEWS LOOP ─────────────────────────────────────────────────────────────────
def news_loop():
    global active_source
    log.info("▶ News watcher started (multi-source with fallback)")
    seed_existing_guids()

    while True:
        try:
            found_any = False
            for source in NEWS_SOURCES:
                items = fetch_rss(source)
                if not items:
                    continue

                # This source is working
                if active_source != source["name"]:
                    log.info(f"  ✅ Active source switched to: {source['name']}")
                    active_source = source["name"]

                new_items = [i for i in items if i["guid"] not in seen_guids]
                for item in new_items:
                    seen_guids.add(item["guid"])
                    impact     = detect_impact(item["title"], item["tags"])
                    currencies = detect_currencies(item["title"])
                    msg = format_news_flash(
                        title=item["title"],
                        source_label=item["label"],
                        url=item["url"],
                        impact=impact,
                        currencies=currencies,
                    )
                    log.info(f"[{item['label']}] NEW: {item['title'][:80]}")
                    broadcast(msg)
                    time.sleep(1)

                found_any = True
                break  # Use only the first working source per cycle

            if not found_any:
                log.warning("⚠️ All RSS sources unavailable this cycle — will retry")

        except Exception as e:
            log.error(f"news_loop error: {e}")

        time.sleep(FJ_POLL_INTERVAL)

# ─── ECONOMIC CALENDAR LOOP ────────────────────────────────────────────────────
def fetch_calendar() -> list:
    """Try all calendar sources, return first successful result."""
    for url in CALENDAR_SOURCES:
        try:
            r = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                log.debug(f"Calendar fetched from {url} — {len(data)} events")
                return data
            else:
                log.warning(f"Calendar HTTP {r.status_code} from {url}")
        except Exception as e:
            log.debug(f"Calendar error [{url}]: {e}")
    return []

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

                # ── Broadcast result when actual is posted ──
                if actual and key not in econ_results_sent:
                    econ_results_sent.add(key)
                    evt_pht = utc_to_pht(evt.get("date", ""), evt.get("time", ""))
                    msg = format_econ_result({
                        **evt,
                        "time": evt_pht,
                    })
                    log.info(f"[ECON RESULT] {evt.get('title')} | Actual={actual}")
                    broadcast(msg)
                    continue

                # ── 30-min warning for high-impact events ──
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
    now = pht_now()
    msg = (
        f"🚀 <b>FJ NEWS BOT v2.0 ONLINE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Started: <b>{now.strftime('%Y-%m-%d %H:%M PHT')}</b>\n\n"
        f"📡 <b>News Sources (auto-fallback):</b>\n"
        f"  1. Financial Juice\n"
        f"  2. ForexLive\n"
        f"  3. FXStreet\n"
        f"  4. DailyFX\n\n"
        f"📅 <b>Economic Calendar:</b>\n"
        f"  • ForexFactory (this week + next week)\n\n"
        f"🔔 <b>You will receive:</b>\n"
        f"  • Live news flashes as they break\n"
        f"  • ⏰ 30-min warnings before high-impact events\n"
        f"  • 📊 Actual vs Forecast results on release"
    )
    broadcast(msg)

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═" * 60)
    log.info("  FJ NEWS BOT v2.0  |  Starting up...")
    log.info("═" * 60)

    MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", 270))
    deadline = time.time() + (MAX_RUNTIME_MINUTES * 60)
    log.info(f"  Runtime limit: {MAX_RUNTIME_MINUTES} min")

    send_startup_banner()

    t1 = Thread(target=news_loop,  daemon=True, name="NEWS")
    t2 = Thread(target=econ_loop,  daemon=True, name="ECON")
    t1.start()
    t2.start()

    log.info("Both watchers running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            if time.time() >= deadline:
                log.info(f"⏰ Runtime limit reached. Exiting cleanly.")
                break
    except KeyboardInterrupt:
        log.info("Shutdown requested. Bye!")
