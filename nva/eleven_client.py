"""Client ElevenLabs : voix off française scène par scène.

Réglages d'expressivité ajustables dans .env sans toucher au code :
  ELEVEN_STABILITY (défaut 0.30 : bas = plus vivant, haut = plus posé)
  ELEVEN_STYLE     (défaut 0.55 : haut = plus expressif/théâtral)
  ELEVEN_SPEED     (défaut 1.10)
  ELEVEN_MODEL     (défaut eleven_multilingual_v2 ; essayer eleven_v3 pour
                    encore plus d'émotion, surtout en mode dialogue)
"""
import os
import subprocess
from pathlib import Path

import requests

from . import config

STABILITY = float(os.environ.get("ELEVEN_STABILITY", "0.30"))
STYLE = float(os.environ.get("ELEVEN_STYLE", "0.55"))
SPEED = float(os.environ.get("ELEVEN_SPEED", "1.10"))


def tts(text: str, dest: Path, voice_id: str | None = None) -> Path:
    if config.DRY_RUN:
        return _placeholder_vo(text, dest)

    voice = voice_id or config.ELEVEN_VOICE_ID
    if not voice:
        raise RuntimeError("ELEVEN_VOICE_ID manquant dans .env (Voices -> copier l'ID)")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    body = {
        "text": text,
        "model_id": config.ELEVEN_MODEL,
        "voice_settings": {"stability": STABILITY, "similarity_boost": 0.8,
                           "style": STYLE, "use_speaker_boost": True},
    }
    r = requests.post(url, headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                      json=body, params={"output_format": "mp3_44100_128"}, timeout=120)
    if r.status_code == 400 and "voice_settings" in r.text:
        # Certains modèles (eleven_v3) refusent ces réglages : on réessaie sans.
        body.pop("voice_settings", None)
        r = requests.post(url, headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                          json=body, params={"output_format": "mp3_44100_128"}, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    # Vitesse appliquée APRÈS coup (ffmpeg atempo) : fiable avec tous les
    # modèles, y compris v3 qui refuse le paramètre côté API. Timbre inchangé.
    if abs(SPEED - 1.0) > 0.01:
        sped = dest.with_name(dest.stem + "_sped.mp3")
        subprocess.run(["ffmpeg", "-y", "-i", str(dest),
                        "-filter:a", f"atempo={SPEED}",
                        "-c:a", "libmp3lame", "-b:a", "128k", str(sped)],
                       check=True, capture_output=True)
        sped.replace(dest)
    return dest


def duration_of(audio_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def _placeholder_vo(text: str, dest: Path) -> Path:
    # ~ 2.5 mots/seconde pour simuler la durée réelle de la voix
    seconds = max(2.0, len(text.split()) / 2.5)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"sine=frequency=440:duration={seconds:.2f}",
        "-filter:a", "volume=0.05", str(dest)
    ], check=True, capture_output=True)
    return dest
