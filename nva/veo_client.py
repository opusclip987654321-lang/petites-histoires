"""Client Veo 3.1 (API Gemini de Google) : clips où les personnages PARLENT.

Contrairement à Grok, Veo génère l'image ET la voix ensemble : lèvres
synchronisées, intonations, sons d'ambiance. Utilisé pour les scènes
"dialogue" ; Grok reste utilisé pour les images de référence.

Contraintes Veo : durées 4, 6 ou 8 s uniquement ; 9:16 ok ; 720p par défaut.
Nécessite GOOGLE_API_KEY dans .env et `pip install google-genai`.
"""
import subprocess
import time
from pathlib import Path

from . import config

_ALLOWED = (4, 6, 8)


def _snap(seconds: float) -> int:
    """Ramène une durée au palier Veo le plus proche (4/6/8 s)."""
    return min(_ALLOWED, key=lambda a: abs(a - seconds))


def generate_video(image_path: Path, prompt: str, seconds: float, dest: Path) -> Path:
    dur = _snap(seconds)
    if config.DRY_RUN:
        return _placeholder(dest, dur)
    if not config.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY manquant dans .env (clé sur aistudio.google.com)")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    image = types.Image(image_bytes=image_path.read_bytes(), mime_type="image/png")
    op = client.models.generate_videos(
        model=config.VEO_MODEL,
        prompt=prompt,
        image=image,
        config=types.GenerateVideosConfig(
            aspect_ratio="9:16",
            duration_seconds=dur,
            resolution=config.VEO_RESOLUTION,
            number_of_videos=1,
        ),
    )
    deadline = time.time() + 15 * 60
    while not op.done:
        if time.time() > deadline:
            raise RuntimeError(f"Veo : délai dépassé (15 min) pour {dest.name}")
        time.sleep(10)
        op = client.operations.get(op)
    if getattr(op, "error", None):
        raise RuntimeError(f"Veo : {op.error}")
    vids = op.response.generated_videos
    if not vids:
        raise RuntimeError("Veo : aucune vidéo renvoyée (prompt refusé ? "
                           "reformuler la scène ou envoyer /retry)")
    client.files.download(file=vids[0].video)
    vids[0].video.save(str(dest))
    return dest


def _placeholder(dest: Path, dur: int) -> Path:
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x224466:s=720x1280:d={dur}:r=24",
        "-f", "lavfi", "-i", f"sine=frequency=330:duration={dur}",
        "-filter:a", "volume=0.05", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(dest),
    ], check=True, capture_output=True)
    return dest
