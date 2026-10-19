"""Générateur d'histoires infini — v3 DIALOGUE (Veo) + codes TikTok.

Quand la banque est vide, Grok (texte, clé xAI) invente une histoire NOUVELLE
au format dialogue : 2-3 personnages qui se parlent, plans courts de 4/6/8 s
animés par Veo (parole native). Charte éditoriale de Louis (26-27/09/2026) :
émotion forte + DRAMA assumé façon TikTok, mais jamais politique, jamais de
célébrité, jamais de chiffre inventé.

Le générateur lit aussi data/published.json (stats Meta collectées par
perf_collect.py) et reçoit un brief « ce qui marche » basé sur les vraies
performances des vidéos précédentes.

Garde-fous : structure validée, durées corrigées (paliers Veo 4/6/8, total
>= 72 s avec l'endcard), endcard de marque ajoutée par le code, alternance
CTA classique / fin discrète, checkpoint images humain avant toute dépense.
"""
import json
import os
import re
import unicodedata

import requests

from . import config

STYLE = ("Viral TikTok stickman cartoon style: characters with big round white heads, "
         "simple expressive dot eyes and bold eyebrows, thin black limbs, thick clean "
         "black outlines, simple flat colorful backgrounds with bold shapes, vibrant "
         "solid colors, funny exaggerated expressions, no text")

ENDCARD = {
    "image_prompt": "",
    "image_file": "assets/branding/endcard.png",
    "motion_prompt": "",
    "duration": 10,
    "still": True,
    "no_character": True,
}

CHARTE = """CHARTE ÉDITORIALE (impérative) :
- CODES TIKTOK : la scène 1 est une ACCROCHE — les 2 premières secondes décident si on scrolle. Pas d'installation, pas de contexte : on ouvre sur une réplique qui intrigue, choque, émeut ou fait rire, et on comprend le contexte en route.
- REGISTRE DE CETTE VIDÉO : {register}. Respecte ce registre, c'est lui qui donne le ton — le catalogue doit rester varié d'une vidéo à l'autre.
- DIALOGUES VIVANTS : répliques courtes qui sonnent vrai, tac-au-tac, sous-entendus. On n'explique pas, on montre. Les personnages ont des défauts et du caractère : personne n'est lisse, personne ne parle comme une publicité.
- ÉMOTION VRAIE sous la surface, quel que soit le registre : solitude, pression familiale sur le mariage, plafond de verre, déclassement. Résolution lumineuse mais jamais mièvre.
- TWIST : chaque histoire contient un retournement (la rivale devient alliée, l'humilié rafle la mise, la personne rencontrée n'est pas celle qu'on croit).
- PROFILS en rotation : 20-25 ans (études, premier job) ; 40-55 ans divorcés ou veufs ; femmes entrepreneuses ; 28-38 ans classiques. Personnages d'origine nord-africaine, dignes et attachants.
- INTERDITS ABSOLUS : aucun parti politique, aucune élection, aucune peur électorale ; aucune célébrité réelle ; aucune statistique inventée ; jamais le mariage comme stratégie administrative ; jamais d'humiliation liée à la religion ou à l'origine.
- La marque Nour Meet n'apparaît qu'à partir de la scène 5, naturellement (un personnage montre l'appli, lance l'invitation au dîner), jamais comme une réclame."""

PROMPT = """Tu écris le scénario d'une vidéo animée TikTok/Reels (55-65 s + écran final) pour Nour Meet : des dîners en petit comité dans de vrais restaurants à Paris/Île-de-France, participants vérifiés — rencontres sérieuses en vue du mariage, et networking professionnel.

FORMAT DIALOGUE (impératif) : 2 ou 3 personnages qui SE PARLENT. Pas de voix off. Chaque plan = 1 à 2 répliques COURTES (12 mots max chacune), car le plan dure 4, 6 ou 8 secondes et les personnages les prononcent réellement à l'écran.

{charte}

{perf}

HISTOIRES DÉJÀ PRODUITES (interdiction de réutiliser ces prénoms, métiers ou situations trop proches) :
{history}

FEUILLETONS EN COURS (personnages récurrents) :
{serials}

CHOIX DU FORMAT : histoire autonome, OU épisode suivant d'un feuilleton en cours (mêmes personnages, descriptions anglaises reprises MOT POUR MOT, l'histoire progresse), OU lancement d'un feuilleton (épisode 1, prévois 2-3 épisodes, termine sur un CLIFFHANGER sec — une porte qui s'ouvre, une phrase coupée, un regard). Ajoute alors "serial": {{"arc": "Prénom", "episode": N, "total": 2 ou 3}}.

AXE de cette histoire : {axis}.
FIN IMPOSÉE : {cta_rule}

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, au format EXACT :
{{
  "title": "Prénoms — accroche courte qui claque",
  "characters": [
    {{
      "key": "prenom_minuscule",
      "name": "Prénom",
      "description": "description physique détaillée EN ANGLAIS : âge, origine nord-africaine, coiffure/barbe dessinée sur la tête ronde, tenue colorée précise (identique dans toutes les scènes), expression typique",
      "genre": "homme ou femme"
    }}
  ],
  "serial": null,
  "scenes": [
    {{
      "dialogue": [
        {{"speaker": "prenom_minuscule", "text": "réplique EN FRANÇAIS, courte, qui claque"}}
      ],
      "cast": ["clés des personnages VISIBLES dans ce plan"],
      "image_prompt": "description visuelle du dessin EN ANGLAIS : QUI est à l'écran, sa pose exagérée, bouche ouverte s'il parle, le décor simple et coloré, les éléments comiques (points d'interrogation, nuage d'orage, étoiles…)",
      "animate": false,
      "motion_prompt": "",
      "duration": 4
    }}
  ],
  "endcard_vo": "la phrase de conclusion FR selon la FIN IMPOSÉE"
}}

FORMAT HYBRIDE (impératif) : choisis les 3 ou 4 PLANS LES PLUS FORTS de l'histoire (l'accroche de la scène 1, le pic d'émotion, le twist, la chute) et mets-leur "animate": true avec un "motion_prompt" EN ANGLAIS décrivant une animation cartoon 2D énergique (bouche qui s'ouvre et se ferme, corps qui rebondit, bras qui s'agitent, éléments du décor qui tremblent). Tous les autres plans gardent "animate": false et un "motion_prompt" vide : ce sont des dessins fixes montés serrés.

Contraintes STRICTES : 8 à 12 scènes ; duration UNIQUEMENT 4 ou 6 ; somme des durations entre 50 et 64 ; EXACTEMENT 3 ou 4 scènes avec "animate": true ; 1 réplique pour un plan de 4 s, 2 répliques max pour un plan de 6 s ; chaque "speaker" est une clé de "characters" ; chaque "cast" liste les personnages à l'écran ; prénoms, métiers et situations ABSENTS des listes ci-dessus (sauf épisode de feuilleton)."""


def _stories() -> list[dict]:
    out = []
    for f in sorted(config.STORIES_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def _char_names(s: dict) -> str:
    if s.get("characters"):
        return ", ".join(c.get("name", "?") for c in s["characters"])
    return s.get("character", {}).get("name", "?")


def _history_summary(stories) -> str:
    lines = [f"- {s.get('title', s.get('id'))} (personnages : {_char_names(s)})"
             for s in stories]
    return "\n".join(lines) if lines else "(aucune)"


def _serials_summary(stories) -> str:
    open_arcs = {}
    for s in stories:
        ser = s.get("serial")
        if ser and ser.get("episode", 1) < ser.get("total", 1):
            open_arcs[ser["arc"]] = (s, ser)
    if not open_arcs:
        return "(aucun feuilleton en cours)"
    out = []
    for arc, (s, ser) in open_arcs.items():
        chars = s.get("characters") or [s.get("character", {})]
        descs = " | ".join(f"{c.get('name')}: {c.get('description', '')}" for c in chars)
        out.append(f"- {arc} : épisode {ser['episode']}/{ser['total']} déjà diffusé — "
                   f"titre « {s['title']} », personnages à réutiliser tels quels : {descs}")
    return "\n".join(out)


def _perf_brief() -> str:
    """Brief « ce qui marche » à partir des stats Meta réelles (perf_collect.py)."""
    f = config.DATA_DIR / "published.json"
    if not f.exists():
        return ""
    try:
        entries = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    lines = []
    for e in entries[-12:]:
        snap = e.get("snapshots", {}).get("d7") or e.get("snapshots", {}).get("h48")
        if not snap:
            continue
        ig = snap.get("instagram", {})
        fb = snap.get("facebook", {})
        bits = []
        for label, d in (("IG", ig), ("FB", fb)):
            if d:
                views = d.get("views") or d.get("plays") or d.get("total_video_views")
                parts = [f"{views} vues" if views is not None else None,
                         f"{d['likes']} likes" if d.get("likes") is not None else None,
                         f"{d['shares']} partages" if d.get("shares") is not None else None,
                         f"{d['comments']} comm." if d.get("comments") is not None else None]
                bits.append(f"{label}: " + ", ".join(p for p in parts if p))
        if bits:
            lines.append(f"- « {e.get('title', e.get('story_id'))} » "
                         f"(format {e.get('format', '?')}, CTA {e.get('cta', '?')}) — "
                         + " | ".join(bits))
    if not lines:
        return ""
    return ("CE QUI MARCHE (statistiques RÉELLES de nos publications — inspire-toi des "
            "recettes des vidéos les plus vues et partagées, sans les copier) :\n"
            + "\n".join(lines) + "\n")


REGISTERS = [
    "DRAMA / CLASH TikTok : gifle verbale d'ouverture, tante toxique, rivalité, "
    "humiliation publique puis revanche élégante — du croustillant, personne n'est lisse",
    "ÉMOTION QUI SERRE LA GORGE : pudeur, silences, détails qui tuent (l'assiette en trop, "
    "le téléphone muet), dignité blessée puis lumière — on vise la larme à l'œil",
    "COMÉDIE : vannes, quiproquos, personnages hauts en couleur, situations absurdes du "
    "célibat et du réseautage — on rit AVEC les personnages, jamais d'eux",
    "SUSPENSE / MYSTÈRE : une phrase intrigante en ouverture, des indices, une révélation "
    "finale qui retourne la vidéo — le spectateur reste pour comprendre",
]


def _next_register(n: int) -> str:
    return REGISTERS[n % len(REGISTERS)]


def _next_axis(n: int) -> str:
    return ["business / entrepreneuriat / réseau professionnel",
            "rencontre sérieuse en vue du mariage",
            "mixte (solitude sociale ET professionnelle)"][n % 3]


def _cta_rule(n: int) -> tuple[str, str]:
    if n % 2 == 0:
        return ("classique", "termine par la morale de l'histoire puis exactement : "
                             "« Nour Meet. Inscris-toi gratuitement. »")
    return ("discret", "termine par UNE seule phrase de morale, poétique et sobre, SANS aucune "
                       "formule publicitaire, sans « inscris-toi », sans nommer la marque "
                       "(l'écran final de marque s'en charge).")


def _slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "histoire"


def _snap_duration(d) -> int:
    return min((4, 6), key=lambda a: abs(a - int(d)))


def _validate_and_fix(data: dict) -> dict:
    for key in ("title", "characters", "scenes", "endcard_vo"):
        if key not in data:
            raise ValueError(f"clé manquante: {key}")
    chars = data["characters"]
    if not 2 <= len(chars) <= 3:
        raise ValueError(f"nombre de personnages invalide: {len(chars)}")
    keys = set()
    for c in chars:
        for key in ("key", "name", "description"):
            if not c.get(key):
                raise ValueError(f"personnage incomplet: {key}")
        if c.get("genre") not in ("homme", "femme"):
            raise ValueError(f"genre manquant ou invalide pour {c.get('name')}")
        keys.add(c["key"])
    scenes = data["scenes"]
    if not 7 <= len(scenes) <= 12:
        raise ValueError(f"nombre de scènes invalide: {len(scenes)}")
    for sc in scenes:
        for key in ("dialogue", "image_prompt", "duration"):
            if key not in sc or not sc[key]:
                raise ValueError(f"scène incomplète: {key}")
        if not 1 <= len(sc["dialogue"]) <= 3:
            raise ValueError("chaque scène doit avoir 1 à 3 répliques")
        for line in sc["dialogue"]:
            if line.get("speaker") not in keys:
                raise ValueError(f"speaker inconnu: {line.get('speaker')}")
            if not line.get("text"):
                raise ValueError("réplique vide")
        sc["duration"] = _snap_duration(sc["duration"])
        sc["cast"] = [k for k in (sc.get("cast") or list(keys)) if k in keys] or list(keys)
        if sc.get("animate") and not sc.get("motion_prompt"):
            raise ValueError("scène animée sans motion_prompt")
    n_anim = sum(1 for sc in scenes if sc.get("animate"))
    if not 2 <= n_anim <= 5:
        raise ValueError(f"il faut 3 ou 4 scènes animées (reçu: {n_anim})")
    anim_secs = sum(sc["duration"] for sc in scenes if sc.get("animate"))
    if anim_secs > 30:
        raise ValueError(f"trop de secondes animées ({anim_secs} > 30) — coût")
    banned = re.compile(r"\b(RN|rassemblement national|élection|zidane|mbapp|benzema)\b", re.I)
    if banned.search(json.dumps(data, ensure_ascii=False)):
        raise ValueError("contenu interdit détecté (politique ou célébrité)")
    def total():
        return sum(sc["duration"] for sc in scenes)
    while total() + 10 < 70:
        cand = next((sc for sc in scenes if sc["duration"] == 4 and not sc.get("animate")), None) \
            or next((sc for sc in scenes if sc["duration"] == 4), None)
        if cand is None:
            raise ValueError("durée totale trop courte : ajoute des scènes")
        cand["duration"] = 6
    while total() + 10 > config.MAX_VIDEO_SECONDS_PER_JOB:
        cand = next((sc for sc in scenes if sc["duration"] == 6 and not sc.get("animate")), None)
        if cand is None:
            break
        cand["duration"] = 4
    return data


# Voix ElevenLabs disponibles ({} = voix par défaut Hugo du .env)
MALE_VOICES = [{}, {"voice_id": "ecxPjiGTvAfpGEams6ec"}]
FEMALE_VOICES = [{"voice_id": "O31r762Gb3WFygrEOGh0"},   # Victoria
                 {"voice_id": "F1toM6PcP54s45kOOAyV"}]  # Koraly


def _assign_voices(chars) -> dict:
    """Chaque personnage reçoit une voix distincte selon son genre."""
    m = f = 0
    speakers = {}
    for c in chars:
        if c.get("genre") == "femme":
            speakers[c["key"]] = dict(FEMALE_VOICES[f % len(FEMALE_VOICES)])
            f += 1
        else:
            speakers[c["key"]] = dict(MALE_VOICES[m % len(MALE_VOICES)])
            m += 1
    return speakers


FACTS_FILE_NAME = "facts.json"


def _pick_fact():
    """Un fait vérifié non utilisé de data/facts.json, ou None."""
    f = config.DATA_DIR / FACTS_FILE_NAME
    if not f.exists():
        return None, None
    facts = json.loads(f.read_text(encoding="utf-8"))
    for i, fact in enumerate(facts):
        if not fact.get("used"):
            return fact, (f, facts, i)
    return None, None


def _mark_fact_used(handle):
    f, facts, i = handle
    facts[i]["used"] = True
    f.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_story() -> dict:
    """Invente, valide et enregistre une nouvelle histoire dialogue. Retourne le dict."""
    if config.DRY_RUN:
        raise RuntimeError("Génération d'histoires désactivée en DRY_RUN.")
    stories = _stories()
    n = len(stories)
    cta_kind, cta_rule = _cta_rule(n)
    # Une vidéo sur trois s'appuie sur un fait VÉRIFIÉ de data/facts.json —
    # cité par UN personnage dans le dialogue, jamais de chiffre inventé.
    fact, fact_handle = (None, None)
    if n % 3 == 2:
        fact, fact_handle = _pick_fact()
    axis = _next_axis(n)
    if fact:
        axis = (f"format « LE SAVIEZ-VOUS » : un personnage cite ce fait RÉEL mot pour mot "
                f"dans une des 3 premières scènes (avec sa source, une seule fois) : "
                f"« {fact['fact']} » (source : {fact['source']}). AUCUN autre chiffre. "
                f"L'histoire incarne ce fait, puis montre l'autre chemin possible")
        cta_kind, cta_rule = _cta_rule(1)  # fin discrète pour l'éditorial
    prompt = PROMPT.format(charte=CHARTE.format(register=_next_register(n)),
                           perf=_perf_brief(),
                           history=_history_summary(stories),
                           serials=_serials_summary(stories),
                           axis=axis, cta_rule=cta_rule)
    model = os.environ.get("XAI_TEXT_MODEL", "grok-4")
    last_error = None
    for _ in range(2):
        messages = [{"role": "user", "content": prompt}]
        if last_error:
            messages.append({"role": "user", "content":
                             f"Ta réponse précédente était invalide ({last_error}). "
                             f"Renvoie UNIQUEMENT le JSON corrigé."})
        r = requests.post(
            f"{config.XAI_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {config.XAI_API_KEY}"},
            json={"model": model, "temperature": 0.9, "messages": messages},
            timeout=240,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = _validate_and_fix(json.loads(match.group(0) if match else text))
            break
        except (ValueError, json.JSONDecodeError, AttributeError) as e:
            last_error = str(e)[:200]
    else:
        raise RuntimeError(f"Grok n'a pas produit d'histoire valide: {last_error}")

    numbers = [int(m.group(1)) for f in config.STORIES_DIR.glob("*.json")
               if (m := re.match(r"(\d+)", f.stem))]
    story_id = f"{max(numbers, default=0) + 1:02d}-{_slugify(data['characters'][0]['name'])}"

    endcard = dict(ENDCARD)
    endcard["vo"] = data["endcard_vo"]
    # Format hybride : les scènes non animées deviennent des dessins fixes.
    for sc in data["scenes"]:
        if sc.pop("animate", False):
            sc.pop("still", None)
        else:
            sc["still"] = True
            sc["motion_prompt"] = ""
    story = {
        "id": story_id,
        "title": data["title"],
        "style": STYLE,
        "characters": data["characters"],
        "speakers": _assign_voices(data["characters"]),
        "scenes": data["scenes"] + [endcard],
        "generated": True,
        "cta": cta_kind,
    }
    if data.get("serial"):
        story["serial"] = data["serial"]
    (config.STORIES_DIR / f"{story_id}.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    if fact_handle:
        _mark_fact_used(fact_handle)
    return story
