"""Configuration centrale de l'agent vidéo Nour Meet."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
STORIES_DIR = BASE_DIR / "stories"
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"

for d in (DATA_DIR, JOBS_DIR, MUSIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

VIDEO_RESOLUTION = os.environ.get("VIDEO_RESOLUTION", "720p")
ELEVEN_VOICE_ID = os.environ.get("ELEVEN_VOICE_ID", "")
ELEVEN_MODEL = os.environ.get("ELEVEN_MODEL", "eleven_multilingual_v2")
MAX_VIDEO_SECONDS_PER_JOB = int(os.environ.get("MAX_VIDEO_SECONDS_PER_JOB", "110"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

XAI_BASE = "https://api.x.ai/v1"
XAI_IMAGE_MODEL = "grok-imagine-image-2.0"
XAI_VIDEO_MODEL = "grok-imagine-video-1.5"

# --- Veo (Google) : scènes dialogue — les personnages parlent réellement ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
VEO_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-fast-generate-preview")
VEO_RESOLUTION = os.environ.get("VEO_RESOLUTION", "720p")
# Moteur des scènes dialogue : "veo" (parole native) ou "grok" (ancien mode)
DIALOGUE_ENGINE = os.environ.get("DIALOGUE_ENGINE", "veo")

# Canevas final 9:16
OUT_W, OUT_H = 1080, 1920
STATE_FILE = DATA_DIR / "state.json"

# --- Publication automatique Instagram/Facebook (API Meta) ---
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
PUBLIC_DIR = DATA_DIR / "public"          # servi par Caddy sur /va/
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://nourmeet.com/va")
AUTO_PUBLISH = os.environ.get("AUTO_PUBLISH", "0") == "1"
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
