"""Publication automatique : Instagram Reels + Facebook Page via l'API Meta.

Prérequis (une fois) :
- Compte Instagram professionnel lié à une Page Facebook.
- App Meta + token longue durée dans .env (META_ACCESS_TOKEN).
- Caddy sert /opt/nour-video-agent/data/public/ sur https://<domaine>/va/
  (l'API Meta vient CHERCHER la vidéo à une URL publique).

La découverte des IDs (Page, compte IG) est automatique et mise en cache.
"""
import json
import secrets
import shutil
import time
from pathlib import Path

import requests

from . import config

GRAPH = f"https://graph.facebook.com/{config.GRAPH_VERSION}"
IDS_CACHE = config.DATA_DIR / "meta_ids.json"


class PublishError(RuntimeError):
    pass


def _get(url, **params):
    params.setdefault("access_token", config.META_ACCESS_TOKEN)
    r = requests.get(url, params=params, timeout=60)
    if not r.ok:
        raise PublishError(f"Meta GET {url.split('/')[-1]}: {r.status_code} {r.text[:300]}")
    return r.json()


def _post(url, **data):
    data.setdefault("access_token", config.META_ACCESS_TOKEN)
    r = requests.post(url, data=data, timeout=120)
    if not r.ok:
        raise PublishError(f"Meta POST {url.split('/')[-1]}: {r.status_code} {r.text[:300]}")
    return r.json()


def discover_ids() -> dict:
    """Trouve la Page FB (+ son token) et le compte Instagram lié. Mis en cache."""
    if IDS_CACHE.exists():
        return json.loads(IDS_CACHE.read_text())
    pages = _get(f"{GRAPH}/me/accounts", fields="id,name,access_token").get("data", [])
    if not pages:
        raise PublishError(
            "Aucune Page Facebook accessible avec ce token. Vérifie que le token a bien "
            "les permissions pages_show_list + pages_manage_posts et que tu es admin de la Page.")
    page = pages[0]
    ig = _get(f"{GRAPH}/{page['id']}", fields="instagram_business_account").get(
        "instagram_business_account")
    if not ig:
        raise PublishError(
            f"La Page « {page['name']} » n'a pas de compte Instagram professionnel lié. "
            "Instagram -> Paramètres -> Centre de comptes -> lier la Page.")
    ids = {"page_id": page["id"], "page_name": page["name"],
           "page_token": page["access_token"], "ig_id": ig["id"]}
    IDS_CACHE.write_text(json.dumps(ids, indent=2))
    return ids


def _expose(video: Path) -> tuple[Path, str]:
    """Copie la vidéo dans le dossier public sous un nom imprévisible."""
    name = f"{secrets.token_urlsafe(16)}.mp4"
    dest = config.PUBLIC_DIR / name
    shutil.copy(video, dest)
    return dest, f"{config.PUBLIC_BASE_URL.rstrip('/')}/{name}"


def default_caption(story: dict, network: str = "ig") -> str:
    hook = story["title"].split("—")[-1].strip()
    cta = ("Inscription gratuite ➜ lien en bio" if network == "ig"
           else "Inscription gratuite ➜ https://nourmeet.com/?utm_source=fb")
    return (f"{hook} 🎬\n\n"
            f"Des soirées en petit comité pour faire de vraies rencontres — "
            f"sérieuses ou professionnelles. Participants vérifiés, à Paris et en Île-de-France.\n"
            f"{cta}\n\n"
            f"#rencontres #networking #paris #mariage #entrepreneur #nourmeet")


def publish_instagram(video_url: str, caption: str, ids: dict) -> str:
    """Publie un Reel. Retourne le permalien."""
    creation = _post(f"{GRAPH}/{ids['ig_id']}/media", media_type="REELS",
                     video_url=video_url, caption=caption, share_to_feed="true")
    creation_id = creation["id"]
    deadline = time.time() + 10 * 60
    while time.time() < deadline:
        time.sleep(10)
        status = _get(f"{GRAPH}/{creation_id}", fields="status_code")
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise PublishError(f"Instagram a rejeté la vidéo: {status}")
    else:
        raise PublishError("Timeout: Instagram n'a pas fini de traiter la vidéo (10 min)")
    media = _post(f"{GRAPH}/{ids['ig_id']}/media_publish", creation_id=creation_id)
    try:
        link = _get(f"{GRAPH}/{media['id']}", fields="permalink").get("permalink", "instagram.com")
    except PublishError:
        link = "https://www.instagram.com/"
    return link, media["id"]


def publish_facebook(video_url: str, caption: str, ids: dict) -> str:
    """Publie la vidéo sur la Page (token de Page requis)."""
    res = requests.post(
        f"{GRAPH}/{ids['page_id']}/videos",
        data={"file_url": video_url, "description": caption,
              "access_token": ids["page_token"]},
        timeout=120,
    )
    if not res.ok:
        raise PublishError(f"Facebook: {res.status_code} {res.text[:300]}")
    vid = res.json().get("id", "")
    return f"https://www.facebook.com/{ids['page_id']}/videos/{vid}", vid


def publish_all(video_path: str, story: dict) -> dict:
    """Publie sur Instagram + Facebook. Retourne {réseau: lien ou 'ERREUR: ...'}."""
    if not config.META_ACCESS_TOKEN:
        return {"info": "META_ACCESS_TOKEN absent du .env — publication auto désactivée."}
    ids = discover_ids()
    exposed, url = _expose(Path(video_path))
    results, media_ids = {}, {}
    try:
        for network, key, fn in (("Instagram", "ig", publish_instagram),
                                 ("Facebook", "fb", publish_facebook)):
            caption = story.get("caption") or default_caption(story, key)
            try:
                results[network], media_ids[key] = fn(url, caption, ids)
            except PublishError as e:
                results[network] = f"ERREUR: {e}"
    finally:
        exposed.unlink(missing_ok=True)
    if media_ids:
        _record_publication(story, media_ids)
    return results


def _record_publication(story: dict, media_ids: dict):
    """Journal des publications (data/published.json) — la matière première de
    perf_collect.py, qui viendra y ranger les stats à 48 h et 7 jours."""
    f = config.DATA_DIR / "published.json"
    entries = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    entries.append({
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "story_id": story.get("id"),
        "title": story.get("title"),
        "format": "dialogue" if any(sc.get("dialogue") for sc in story.get("scenes", [])) else "vo",
        "cta": story.get("cta"),
        "serial": story.get("serial"),
        "ig_media_id": media_ids.get("ig"),
        "fb_video_id": media_ids.get("fb"),
        "snapshots": {},
    })
    f.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
