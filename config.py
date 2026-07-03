"""
═══════════════════════════════════════
  FJ NEWS BOT — Configuration
  Edit these values before running!
═══════════════════════════════════════
"""

# ─── TELEGRAM ──────────────────────────────────────────────────────────────────
# Get your bot token from @BotFather on Telegram
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# Channel IDs (use negative numbers for channels, e.g. -1001234567890)
# To get channel ID: forward a message from your channel to @userinfobot
CHANNEL_COT = "@CircleOfTraders"    # or use numeric ID like -1001234567890
CHANNEL_MCR = "@MCROTRADES"        # or use numeric ID

# ─── POLLING INTERVALS ────────────────────────────────────────────────────────
# How often to check Financial Juice RSS (seconds)
# Recommended: 90–120 seconds (too fast may get rate-limited)
FJ_POLL_INTERVAL = 90

# How often to check the economic calendar for new results (seconds)
# Recommended: 60–120 seconds
ECON_POLL_INTERVAL = 60

# ─── FILTERS ──────────────────────────────────────────────────────────────────
# Which FJ categories to monitor (True = enabled)
FJ_CATEGORIES = {
    "forex":    True,   # Forex-specific news
    "macro":    True,   # Macro / central bank news
    "market":   True,   # Market-moving news
    "all":      False,  # ALL news (very high volume — enable only if needed)
}

# Minimum impact level for FJ news to be broadcast
# Options: "low", "medium", "high"
# "high" = only central bank / major data news
# "low"  = everything (noisy)
FJ_MIN_IMPACT = "low"   # Start with "low" and raise if too noisy

# Only broadcast economic events with these impact levels
# Options: ["High"], ["High", "Medium"]
ECON_IMPACT_FILTER = ["High", "Medium"]
