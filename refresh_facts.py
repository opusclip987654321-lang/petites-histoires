"""Rafraîchit la banque de faits (data/facts.json) avec l'actualité récente,
via la recherche en temps réel de Grok (clé xAI existante). Lancé par cron
chaque semaine. Seuls les faits accompagnés de sources/citations sont acceptés —
jamais de chiffre sans origine. Le checkpoint Telegram reste le contrôle final.

Usage : venv/bin/python refresh_facts.py
Cron  : 0 8 * * 1  (chaque lundi 8h UTC / 10h Paris)
"""
import json
import re

import requests

from nva import config

FACTS = config.DATA_DIR / "facts.json"

PROMPT = """Cherche sur le web des faits et chiffres RÉCENTS (moins de 3 mois si possible, sinon moins d'un an) concernant la FRANCE, publiés par des sources fiables (INSEE, INED, grandes fondations, instituts de sondage reconnus, presse nationale), sur ces thèmes :
- la solitude et l'isolement social
- le célibat, les rencontres, la formation des couples
- l'insertion professionnelle des jeunes diplômés, le rôle du réseau dans l'emploi
- l'entrepreneuriat (notamment des femmes et des quartiers populaires)

Réponds UNIQUEMENT avec un tableau JSON de 3 éléments maximum :
[{"fact": "le fait formulé en une phrase française claire avec son chiffre exact", "source": "Nom de la source, année", "url": "https://..."}]

Règles strictes : uniquement des faits que tu as réellement trouvés dans tes recherches, avec l'URL de la page consultée ; aucun chiffre approximatif ou de mémoire ; aucun sujet politique ou électoral."""


def main():
    existing = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.exists() else []
    known_urls = {f.get("url") for f in existing if f.get("url")}
    known_facts = [f["fact"] for f in existing]

    body = {
        "model": __import__("os").environ.get("XAI_TEXT_MODEL", "grok-4"),
        "messages": [{"role": "user", "content": PROMPT}],
        "search_parameters": {"mode": "on", "return_citations": True},
    }
    r = requests.post(f"{config.XAI_BASE}/chat/completions",
                      headers={"Authorization": f"Bearer {config.XAI_API_KEY}"},
                      json=body, timeout=300)
    if r.status_code == 400 and "search_parameters" in r.text:
        raise SystemExit("L'API a refusé la recherche en direct (search_parameters) — "
                         "vérifier la doc xAI, on n'ajoute AUCUN fait non sourcé.")
    r.raise_for_status()
    payload = r.json()
    text = payload["choices"][0]["message"]["content"]
    citations = set(payload.get("citations") or
                    payload["choices"][0]["message"].get("citations") or [])

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise SystemExit("Pas de JSON dans la réponse — aucun fait ajouté.")
    candidates = json.loads(match.group(0))

    added = []
    for c in candidates:
        fact, source, url = c.get("fact"), c.get("source"), c.get("url")
        if not (fact and source and url):
            continue
        if url in known_urls or any(fact[:40] in k for k in known_facts):
            continue  # doublon
        if citations and url not in citations:
            # l'URL annoncée ne fait pas partie des pages réellement consultées
            continue
        existing.append({"fact": fact, "source": source, "url": url, "used": False})
        added.append(f"• {fact}\n  ({source} — {url})")

    if added:
        FACTS.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # Notification Telegram
    cid = config.TELEGRAM_CHAT_ID or (config.DATA_DIR / "chat_id.txt").read_text().strip()
    msg = ("🗞 Banque de faits — " +
           (f"{len(added)} nouveau(x) fait(s) vérifié(s) ajouté(s) :\n\n" + "\n\n".join(added)
            if added else "rien de nouveau cette semaine (aucun fait sourcé retenu)."))
    requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                  data={"chat_id": cid, "text": msg[:4000]}, timeout=60)
    print(f"{len(added)} fait(s) ajouté(s).")


if __name__ == "__main__":
    main()
