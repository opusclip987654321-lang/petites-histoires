"""Test Veo à petit prix : génère les N premières scènes dialogue d'une histoire
(images Grok + clips Veo où les personnages parlent), les colle, et envoie le
résultat sur Telegram. Ne touche pas au job en cours du bot.

Usage : venv/bin/python test_veo.py                 (2 scènes de l'histoire 12)
        venv/bin/python test_veo.py 12-leila-samia-v2 3   (3 scènes)
Coût : ~1,1 $ par scène de 8 s (Veo 0,15 $/s + image Grok).
"""
import sys
from pathlib import Path

import requests

from nva import assemble, config, pipeline, veo_client, xai_client

story_id = sys.argv[1] if len(sys.argv) > 1 else "12-leila-samia-v2"
count = int(sys.argv[2]) if len(sys.argv) > 2 else 2

story = pipeline.load_story(story_id)
scenes = [s for s in story["scenes"] if s.get("dialogue")][:count]
work = config.DATA_DIR / "test_veo" / story_id
work.mkdir(parents=True, exist_ok=True)

print(f"— Fiches personnages (Grok, mises en cache)…")
refs = pipeline.character_refs(story)

built = []
for i, scene in enumerate(scenes):
    n = i + 1
    image = work / f"scene_{n:02d}.png"
    if not image.exists():
        print(f"— Scène {n}/{len(scenes)} : image Grok…")
        xai_client.generate_image(pipeline._image_prompt(story, scene), image,
                                  reference_paths=pipeline._scene_refs(story, scene, refs))
    clip = work / f"clip_{n:02d}.mp4"
    if not clip.exists():
        print(f"— Scène {n}/{len(scenes)} : Veo ({scene['duration']} s, parole native)…")
        veo_client.generate_video(image, pipeline._veo_prompt(story, scene),
                                  scene["duration"], clip)
    final = work / f"final_{n:02d}.mp4"
    if not final.exists():
        assemble.conform_clip(clip, final)
    built.append(final)

out = assemble.concat_scenes(built, work / "TEST_VEO.mp4")
print(f"OK : {out}")

cid = config.TELEGRAM_CHAT_ID or (config.DATA_DIR / "chat_id.txt").read_text().strip()
with open(out, "rb") as f:
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendVideo",
        data={"chat_id": cid, "width": 1080, "height": 1920,
              "caption": f"🧪 Test Veo — {len(built)} scène(s) de « {story['title']} »"},
        files={"video": f}, timeout=300)
print("Envoyé sur Telegram" if r.ok else f"Envoi Telegram raté : {r.text[:200]}")
