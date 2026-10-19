"""Sous-titres automatiques des scènes dialogue Veo.

La voix est générée PAR Veo dans le clip, donc on ne connaît pas le minutage
des répliques. On transcrit l'audio du clip avec Whisper (faster-whisper, sur
le CPU du VPS) pour obtenir les horodatages, mais on affiche le TEXTE EXACT du
scénario (jamais la transcription, qui peut se tromper) : Whisper donne le
« quand », le scénario donne le « quoi ».

Style par locuteur (blanc / safran) comme l'ancien mode dialogue.
Nécessite : venv/bin/pip install faster-whisper  (premier lancement : le
modèle ~460 Mo se télécharge une fois dans ~/.cache).
"""
import os
from pathlib import Path

from . import config
from .eleven_client import duration_of

_MODEL = None


def _model():
    global _MODEL  # noqa: PLW0603
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(os.environ.get("WHISPER_MODEL", "small"),
                              device="cpu", compute_type="int8")
    return _MODEL


def _styles(scene: dict) -> dict:
    styles = {}
    for line in scene["dialogue"]:
        spk = line["speaker"]
        if spk not in styles:
            styles[spk] = "Sub" if len(styles) % 2 == 0 else "Sub2"
    return styles


def _proportional(lines, t0: float, t1: float, styles: dict):
    """Répartit les répliques entre t0 et t1 au prorata de leur longueur."""
    total = sum(len(line["text"]) for line in lines) or 1
    events, cursor = [], t0
    for line in lines:
        dur = (t1 - t0) * len(line["text"]) / total
        events.append([round(cursor, 2), round(cursor + dur - 0.1, 2),
                       line["text"], styles[line["speaker"]]])
        cursor += dur
    return events


def dialogue_events(clip: Path, scene: dict):
    """[(start, end, texte, style), ...] pour une scène dialogue, ou None."""
    lines = scene.get("dialogue") or []
    if not lines:
        return None
    styles = _styles(scene)
    if config.DRY_RUN:
        return _proportional(lines, 0.3, max(duration_of(clip) - 0.3, 1.0), styles)
    segments, _info = _model().transcribe(str(clip), language="fr", vad_filter=True)
    segs = [(s.start, s.end) for s in segments if s.text.strip()]
    if not segs:
        return None
    if len(segs) == len(lines):
        return [[round(s0, 2), round(s1, 2), line["text"], styles[line["speaker"]]]
                for (s0, s1), line in zip(segs, lines)]
    return _proportional(lines, segs[0][0], segs[-1][1], styles)
