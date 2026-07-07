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

# ─── AI — Google Gemini (FREE) ─────────────────────────────────────────────────
# Get free key at: aistudio.google.com → Get API Key → Create API key
# Key starts with AIza...
GROQ_API_KEY   = ""                                    # disabled
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # active

# ─── POLLING INTERVALS ────────────────────────────────────────────────────────
FJ_POLL_INTERVAL   = int(os.environ.get("FJ_POLL_INTERVAL",   90))
ECON_POLL_INTERVAL = int(os.environ.get("ECON_POLL_INTERVAL", 300))

# ─── FILTERS ──────────────────────────────────────────────────────────────────
FJ_CATEGORIES = {
    "forex":  True,
    "macro":  True,
    "market": True,
    "all":    False,
}

FJ_MIN_IMPACT      = "low"
ECON_IMPACT_FILTER = ["High", "Medium"]
