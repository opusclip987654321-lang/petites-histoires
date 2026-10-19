"""Reconstruit la vidéo finale d'un job déjà produit avec l'endcard actuelle,
sans regénérer les scènes payées, puis l'envoie sur Telegram.

Usage : venv/bin/python rebuild_final.py            (dernier job)
        venv/bin/python rebuild_final.py <job_id>   (job précis)
"""
import shutil
import sys

import requests

from nva import assemble, config, eleven_client, pipeline

jobs = sorted(p.name for p in config.JOBS_DIR.iterdir() if p.is_dir())
if not jobs:
    raise SystemExit("Aucun job dans data/jobs/")
job_id = sys.argv[1] if len(sys.argv) > 1 else jobs[-1]
job_dir = config.JOBS_DIR / job_id
story = pipeline.load_story(job_id.rsplit("-", 2)[0])

n = len(story["scenes"])
last = story["scenes"][-1]
if not last.get("image_file"):
    raise SystemExit("La dernière scène de cette histoire n'utilise pas d'endcard fixe.")

print(f"Job : {job_id} — remplacement de la scène {n} par l'endcard…")
img = job_dir / "images" / f"scene_{n:02d}.png"
shutil.copy(config.BASE_DIR / last["image_file"], img)

clip = job_dir / "clips" / f"clip_{n:02d}.mp4"
clip.unlink(missing_ok=True)
assemble.still_to_clip(img, last["duration"], clip)

vo = job_dir / "audio" / f"vo_{n:02d}.mp3"
if not vo.exists():
    eleven_client.tts(last["vo"], vo)

built = job_dir / f"scene_{n:02d}_final.mp4"
built.unlink(missing_ok=True)
assemble.build_scene(clip, vo, last["vo"], built, min_duration=float(last["duration"]))

print("Remontage…")
scene_files = [job_dir / f"scene_{i + 1:02d}_final.mp4" for i in range(n)]
missing = [f.name for f in scene_files if not f.exists()]
if missing:
    raise SystemExit(f"Scènes manquantes dans ce job : {missing}")
merged = assemble.concat_scenes(scene_files, job_dir / "merged.mp4")
final = assemble.add_music(merged, job_dir / f"{job_id}_FINAL_v2.mp4")

cid = config.TELEGRAM_CHAT_ID or (config.DATA_DIR / "chat_id.txt").read_text().strip()
print("Envoi sur Telegram…")
with open(final, "rb") as f:
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendVideo",
        data={"chat_id": cid, "width": 1080, "height": 1920,
              "supports_streaming": "true",
              "caption": f"🎬 {story['title']} — version avec écran final de marque"},
        files={"video": f}, timeout=600,
    ).raise_for_status()
print(f"OK : {final}")
