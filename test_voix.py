"""Test A/B des modèles de voix ElevenLabs : la même réplique en v2 et en v3,
envoyée sur Telegram. Coût : quelques centimes.

Usage : venv/bin/python test_voix.py
"""
import os

import requests

TEXT = "Sofiane ?! Depuis quand tu livres des sushis, toi ? T'as un master en marketing !"
VOICE = "ecxPjiGTvAfpGEams6ec"  # la voix choisie pour Rayan

from nva import config  # noqa: E402

for label, model in (("V2 (ancien)", "eleven_multilingual_v2"), ("V3 (expressif)", "eleven_v3")):
    os.environ["ELEVEN_MODEL"] = model
    config.ELEVEN_MODEL = model
    from nva import eleven_client
    eleven_client.__dict__["config"].ELEVEN_MODEL = model
    dest = config.DATA_DIR / f"test_{model}.mp3"
    try:
        eleven_client.tts(TEXT, dest, voice_id=VOICE)
    except Exception as e:  # noqa: BLE001
        print(f"{label} : ÉCHEC ({str(e)[:200]})")
        continue
    cid = config.TELEGRAM_CHAT_ID or (config.DATA_DIR / "chat_id.txt").read_text().strip()
    with open(dest, "rb") as f:
        requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendAudio",
                      data={"chat_id": cid, "title": label, "caption": f"🎙 {label}"},
                      files={"audio": f}, timeout=120)
    print(f"{label} : envoyé sur Telegram")
