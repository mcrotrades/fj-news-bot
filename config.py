import os

BOT_TOKEN   = os.environ.get("BOT_TOKEN",   "8745138732:AAEkC_sE9W4TCr7Mh7ieW6UvhXDKmHHEbM8")
CHANNEL_COT = os.environ.get("CHANNEL_COT", "-1004370012411")
CHANNEL_MCR = os.environ.get("CHANNEL_MCR", "-1004370012411")

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

FJ_POLL_INTERVAL   = int(os.environ.get("FJ_POLL_INTERVAL",   90))
ECON_POLL_INTERVAL = int(os.environ.get("ECON_POLL_INTERVAL", 300))

FJ_CATEGORIES      = {"forex": True, "macro": True, "market": True, "all": False}
FJ_MIN_IMPACT      = "low"
ECON_IMPACT_FILTER = ["High", "Medium"]
