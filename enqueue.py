"""Lancé par cron tous les 2 jours : met la prochaine histoire en file.
Si la banque est vide, le générateur invente une histoire nouvelle (Grok texte,
charte éditoriale) — le checkpoint images sur Telegram reste ta validation.
Le bot (bot.py) détecte le job et déroule le pipeline.
"""
from nva import pipeline, state as state_mod, story_gen

st = state_mod.load()
if st and st["stage"] not in ("published", "rejected"):
    print(f"Job déjà en cours ({st['stage']}), on ne lance rien.")
else:
    story = pipeline.next_story()
    if story is None:
        print("Banque vide -> génération d'une nouvelle histoire…")
        story = story_gen.generate_story()
        print(f"Histoire inventée : {story['title']}")
    state_mod.new_job(story)
    print(f"Job créé : {story['title']}")
