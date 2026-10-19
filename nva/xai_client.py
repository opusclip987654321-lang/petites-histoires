"""Client xAI Grok Imagine : génération d'images (avec références) et image-to-video.

Docs: https://docs.x.ai — endpoints:
  POST /v1/images/generations   (texte -> image)
  POST /v1/images/edits         (références/édition -> image, jusqu'à 5 images source)
  POST /v1/videos/generations   (image -> vidéo, asynchrone)
  GET  /v1/videos/{request_id}  (polling: status done|failed|expired)
"""
import base64
import subprocess
import time
from pathlib import Path

import requests

from . import config

HEADERS = {"Authorization": f"Bearer {config.XAI_API_KEY}"}
TIMEOUT = 120


def _b64_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _download(url: str, dest: Path) -> Path:
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def _extract_image_url(payload: dict) -> str:
    # Réponse style OpenAI: {"data": [{"url": ...}]} ou {"data": [{"b64_json": ...}]}
    data = (payload.get("data") or [{}])[0]
    if data.get("url"):
        return data["url"]
    if data.get("b64_json"):
        return "b64:" + data["b64_json"]
    if payload.get("url"):
        return payload["url"]
    raise RuntimeError(f"Réponse image inattendue: {list(payload.keys())}")


def _save_image_result(result: str, dest: Path) -> Path:
    if result.startswith("b64:"):
        dest.write_bytes(base64.b64decode(result[4:]))
        return dest
    return _download(result, dest)


def generate_image(prompt: str, dest: Path, reference_paths=None) -> Path:
    """Génère une image 9:16. Avec reference_paths -> endpoint /images/edits
    pour garder le personnage cohérent (max 5 références)."""
    if config.DRY_RUN:
        return _placeholder_image(prompt, dest)

    if reference_paths:
        body = {
            "model": config.XAI_IMAGE_MODEL,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "image_urls": [_b64_data_uri(Path(p)) for p in reference_paths[:5]],
        }
        url = f"{config.XAI_BASE}/images/edits"
    else:
        body = {"model": config.XAI_IMAGE_MODEL, "prompt": prompt,
                "aspect_ratio": "9:16"}
        url = f"{config.XAI_BASE}/images/generations"

    r = requests.post(url, json=body, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 400 and "aspect_ratio" in r.text:
        body.pop("aspect_ratio", None)  # champ non supporté -> on retente sans
        r = requests.post(url, json=body, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 400 and reference_paths and "image_urls" in r.text:
        # Certains déploiements attendent "image_url" (une seule référence)
        body.pop("image_urls")
        body["image_url"] = _b64_data_uri(Path(reference_paths[0]))
        r = requests.post(url, json=body, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return _save_image_result(_extract_image_url(r.json()), dest)


def generate_video(image_path: Path, motion_prompt: str, duration: int, dest: Path) -> Path:
    """Anime une image en clip vidéo (asynchrone: POST puis polling)."""
    if config.DRY_RUN:
        return _placeholder_clip(image_path, duration, dest)

    body = {
        "model": config.XAI_VIDEO_MODEL,
        "prompt": motion_prompt,
        "image": {"url": _b64_data_uri(image_path)},
        "duration": duration,
        "aspect_ratio": "9:16",
        "resolution": config.VIDEO_RESOLUTION,
    }
    r = requests.post(f"{config.XAI_BASE}/videos/generations", json=body,
                      headers=HEADERS, timeout=TIMEOUT)
    for field in ("aspect_ratio", "resolution"):
        if r.status_code == 400 and field in r.text:
            body.pop(field, None)  # champ non supporté -> on retente sans
            r = requests.post(f"{config.XAI_BASE}/videos/generations", json=body,
                              headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    request_id = r.json().get("request_id") or r.json().get("id")
    if not request_id:
        raise RuntimeError(f"Pas de request_id dans la réponse: {r.json()}")

    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        time.sleep(6)
        p = requests.get(f"{config.XAI_BASE}/videos/{request_id}",
                         headers=HEADERS, timeout=TIMEOUT)
        p.raise_for_status()
        js = p.json()
        status = js.get("status")
        if status == "done":
            video_url = (js.get("video") or {}).get("url") or js.get("url")
            return _download(video_url, dest)
        if status in ("failed", "expired"):
            raise RuntimeError(f"Génération vidéo {status}: {js}")
    raise TimeoutError("Timeout génération vidéo (15 min)")


# ---------- Mode DRY_RUN : assets factices via ffmpeg (aucun coût) ----------

def _placeholder_image(prompt: str, dest: Path) -> Path:
    txt = prompt.replace("'", "").replace(":", " ")[:60]
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=0x1e2a4a:s={config.OUT_W}x{config.OUT_H}:d=1",
        "-vf", f"drawtext=text='{txt}':fontcolor=white:fontsize=36:"
               f"x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v", "1", str(dest)
    ], check=True, capture_output=True)
    return dest


def _placeholder_clip(image_path: Path, duration: int, dest: Path) -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
        "-t", str(duration), "-r", "24",
        "-vf", "scale=720:1280", "-pix_fmt", "yuv420p", str(dest)
    ], check=True, capture_output=True)
    return dest
