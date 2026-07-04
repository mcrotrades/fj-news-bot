"""
═══════════════════════════════════════
  FJ NEWS BOT v3.0 — Configuration
═══════════════════════════════════════
"""
import os

# ─── TELEGRAM ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN",   "8745138732:AAEkC_sE9W4TCr7Mh7ieW6UvhXDKmHHEbM8")
CHANNEL_COT = os.environ.get("CHANNEL_COT", "-1004370012411")
CHANNEL_MCR = os.environ.get("CHANNEL_MCR", "-1004370012411")

# ─── GROQ AI (FREE) ────────────────────────────────────────────────────────────
# Get your FREE API key from: https://console.groq.com
# Sign up → API Keys → Create API Key → starts with gsk_...
GROQ_API_KEY = os.environ.get("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")

# ─── POLLING INTERVALS ────────────────────────────────────────────────────────
FJ_POLL_INTERVAL   = int(os.environ.get("FJ_POLL_INTERVAL",   90))
ECON_POLL_INTERVAL = int(os.environ.get("ECON_POLL_INTERVAL", 60))

# ─── FILTERS ──────────────────────────────────────────────────────────────────
FJ_CATEGORIES = {
    "forex":  True,
    "macro":  True,
    "market": True,
    "all":    False,
}

FJ_MIN_IMPACT      = "low"
ECON_IMPACT_FILTER = ["High", "Medium"]
