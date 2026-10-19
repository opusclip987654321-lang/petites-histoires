"""Boucle d'apprentissage : collecte les statistiques Meta des vidéos publiées.

Pour chaque vidéo de data/published.json, prend une photo des stats à 48 h
puis à 7 jours (vues, portée, likes, commentaires, partages, enregistrements),
la range dans le même fichier, et envoie un mini-bilan sur Telegram. Le
générateur d'histoires (story_gen) lit ensuite ces chiffres pour écrire en
s'inspirant de ce qui marche vraiment.

Usage : venv/bin/python perf_collect.py
Cron  : 30 9 * * *  (tous les jours à ~11h30 Paris)
"""
import json
import time
from datetime import datetime

import requests

from nva import config, publisher

PUB = config.DATA_DIR / "published.json"

IG_METRICS = ["views", "reach", "likes", "comments", "shares", "saved"]
FB_METRICS = ["total_video_views", "total_video_impressions"]


def _ig_stats(media_id: str) -> dict:
    out = {}
    for metric in IG_METRICS:
        try:
            data = publisher._get(  # noqa: SLF001
                f"{publisher.GRAPH}/{media_id}/insights", metric=metric).get("data", [])
            for d in data:
                values = d.get("values") or [{}]
                out[d["name"]] = values[0].get("value")
        except publisher.PublishError:
            continue
    return out


def _fb_stats(video_id: str, page_token: str) -> dict:
    out = {}
    try:
        r = requests.get(f"{publisher.GRAPH}/{video_id}/video_insights",
                         params={"access_token": page_token}, timeout=60)
        if r.ok:
            for d in r.json().get("data", []):
                name = d.get("name", "")
                values = d.get("values") or [{}]
                if name in FB_METRICS or "views" in name:
                    out[name] = values[0].get("value")
    except requests.RequestException:
        pass
    return out


def _fmt(snap: dict) -> str:
    bits = []
    for label, d in (("IG", snap.get("instagram", {})), ("FB", snap.get("facebook", {}))):
        if d:
            views = d.get("views") or d.get("total_video_views")
            parts = [f"{views} vues" if views is not None else None,
                     f"{d['likes']} ❤️" if d.get("likes") is not None else None,
                     f"{d['comments']} 💬" if d.get("comments") is not None else None,
                     f"{d['shares']} ↪️" if d.get("shares") is not None else None]
            bits.append(f"{label} : " + ", ".join(p for p in parts if p))
    return " | ".join(bits) or "aucune stat disponible"


def main():
    if not PUB.exists():
        print("Aucune publication enregistrée.")
        return
    entries = json.loads(PUB.read_text(encoding="utf-8"))
    try:
        ids = publisher.discover_ids()
    except publisher.PublishError as e:
        print(f"Meta inaccessible: {e}")
        return
    now = time.time()
    reports = []
    for e in entries:
        try:
            age_h = (now - datetime.fromisoformat(e["date"]).timestamp()) / 3600
        except (KeyError, ValueError):
            continue
        snaps = e.setdefault("snapshots", {})
        for label, hours in (("h48", 48), ("d7", 168)):
            if label in snaps or age_h < hours:
                continue
            snap = {}
            if e.get("ig_media_id"):
                snap["instagram"] = _ig_stats(e["ig_media_id"])
            if e.get("fb_video_id"):
                snap["facebook"] = _fb_stats(e["fb_video_id"], ids.get("page_token", ""))
            snaps[label] = snap
            horizon = "48 h" if label == "h48" else "7 jours"
            reports.append(f"📊 « {e.get('title', e.get('story_id'))} » à {horizon} :\n{_fmt(snap)}")
    if reports:
        PUB.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        cid = config.TELEGRAM_CHAT_ID or (config.DATA_DIR / "chat_id.txt").read_text().strip()
        requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": cid,
                            "text": ("\n\n".join(reports))[:4000]}, timeout=60)
    print(f"{len(reports)} bilan(s) collecté(s).")


if __name__ == "__main__":
    main()
