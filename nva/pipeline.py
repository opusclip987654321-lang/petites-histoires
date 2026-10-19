"""Les étapes du pipeline : histoires -> images -> clips -> voix -> vidéo finale."""
import json
import shutil
import subprocess
from pathlib import Path

from . import assemble, config, eleven_client, state as state_mod, subtitles, veo_client, xai_client


def load_story(story_id: str) -> dict:
    return json.loads((config.STORIES_DIR / f"{story_id}.json").read_text(encoding="utf-8"))


def _history() -> list:
    f = config.DATA_DIR / "history.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def mark_done(story_id: str):
    f = config.DATA_DIR / "history.json"
    h = _history()
    h.append(story_id)
    f.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


def next_story():
    """Prochaine histoire jamais produite (ordre alphabétique des fichiers)."""
    done = set(_history())
    for f in sorted(config.STORIES_DIR.glob("*.json")):
        if f.stem not in done:
            return load_story(f.stem)
    return None


def _characters(story: dict) -> list:
    """Liste des personnages : format v2 ("characters") ou v1 ("character")."""
    if story.get("characters"):
        return story["characters"]
    c = story["character"]
    return [{"key": "main", "name": c["name"], "description": c["description"]}]


def _cast(story: dict, scene: dict) -> list:
    chars = {c["key"]: c for c in _characters(story)}
    keys = scene.get("cast") or list(chars)
    return [chars[k] for k in keys if k in chars]


def _image_prompt(story: dict, scene: dict) -> str:
    descs = ". ".join(c["description"] for c in _cast(story, scene))
    parts = [story["style"], descs, scene["image_prompt"],
             "vertical 9:16 composition, no text, no captions, no watermark"]
    return ". ".join(p.strip().rstrip(".") for p in parts if p)


def character_refs(story: dict) -> dict:
    """Fiches personnages (2-3 vues chacune), générées une fois et mises en cache.
    Retourne {clé personnage: [chemins]}."""
    ref_dir = config.STORIES_DIR / "refs" / story["id"]
    ref_dir.mkdir(parents=True, exist_ok=True)
    chars = _characters(story)
    views = (["front portrait", "three-quarter portrait", "full body standing"]
             if len(chars) == 1 else ["front portrait", "three-quarter portrait"])
    all_refs = {}
    for char in chars:
        prefix = "ref" if char["key"] == "main" else char["key"]
        refs = []
        for i, view in enumerate(views):
            dest = ref_dir / f"{prefix}_{i}.png"
            if not dest.exists():
                prompt = (f"{story['style']}. Character sheet, {view}, neutral plain background. "
                          f"{char['description']}. Same face, same outfit.")
                xai_client.generate_image(prompt, dest,
                                          reference_paths=[refs[0]] if refs else None)
            refs.append(dest)
        all_refs[char["key"]] = refs
    return all_refs


def _scene_refs(story: dict, scene: dict, all_refs: dict) -> list | None:
    if scene.get("no_character"):
        return None
    refs = []
    for c in _cast(story, scene):
        refs.extend(str(r) for r in all_refs.get(c["key"], []))
    return refs[:5] or None


def stage_images(state: dict) -> dict:
    story = load_story(state["story_id"])
    refs = character_refs(story)
    job_dir = Path(state["job_dir"])
    for i, scene in enumerate(story["scenes"]):
        dest = job_dir / "images" / f"scene_{i + 1:02d}.png"
        if not dest.exists():
            if scene.get("image_file"):
                src = config.BASE_DIR / scene["image_file"]
                if not src.exists():
                    raise RuntimeError(
                        f"Scène {i + 1}: fichier manquant '{scene['image_file']}' — "
                        f"dépose ton visuel (1080x1920 PNG/JPG) à cet emplacement "
                        f"dans /opt/nour-video-agent/ puis envoie /retry")
                shutil.copy(src, dest)
            else:
                xai_client.generate_image(_image_prompt(story, scene), dest,
                                          reference_paths=_scene_refs(story, scene, refs))
        state["scenes"][i]["image"] = str(dest)
    state["stage"] = "images_done"
    return state_mod.save(state)


def regen_image(state: dict, scene_number: int, note: str = "") -> dict:
    """Regénère l'image d'une scène (1-based), avec consigne optionnelle."""
    story = load_story(state["story_id"])
    i = scene_number - 1
    scene = story["scenes"][i]
    if scene.get("image_file"):
        raise RuntimeError(
            f"La scène {scene_number} utilise un fichier fixe ({scene['image_file']}) : "
            f"remplace ce fichier sur le VPS au lieu de /regen.")
    dest = Path(state["job_dir"]) / "images" / f"scene_{scene_number:02d}.png"
    dest.unlink(missing_ok=True)
    prompt = _image_prompt(story, scene) + (f". {note}" if note else "")
    xai_client.generate_image(prompt, dest,
                              reference_paths=_scene_refs(story, scene, character_refs(story)))
    state["scenes"][i]["image"] = str(dest)
    return state_mod.save(state)


def _similarity(a: Path, b: Path) -> float:
    """Score SSIM 0..1 entre deux images (via ffmpeg). 1 = identiques."""
    import re as _re
    p = subprocess.run(
        ["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi",
         "[0:v][1:v]scale2ref[x][y];[x][y]ssim", "-f", "null", "-"],
        capture_output=True, text=True)
    m = _re.search(r"All:(\d+\.\d+)", p.stderr)
    return float(m.group(1)) if m else 0.0


def _veo_prompt(story: dict, scene: dict) -> str:
    """Prompt Veo pour une scène dialogue : les personnages parlent réellement
    (lèvres synchro, voix générées). Les répliques sont données mot pour mot."""
    cast = _cast(story, scene)
    names = {c["key"]: c["name"] for c in cast}
    descs = ". ".join(c["description"] for c in cast)
    voices = ". ".join(f"{c['name']} has a {c['voice']}" for c in cast if c.get("voice"))
    lines = "\n".join(
        f'{names.get(d["speaker"], d["speaker"].capitalize())} says in French: "{d["text"]}"'
        for d in scene["dialogue"])
    parts = [
        story["style"], descs,
        scene.get("image_prompt", ""), scene.get("motion_prompt", ""),
        "Dialogue, spoken in French with natural Parisian accents, "
        "lips perfectly synchronized with the words:\n" + lines,
        voices,
        "No subtitles, no captions, no on-screen text, no watermark. "
        "Vertical 9:16 composition.",
    ]
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())


def _build_dialogue_audio(story: dict, scene: dict, vo_dest: Path, subs_dest: Path):
    """Mode dialogue : une voix par personnage, audio de scène assemblé réplique
    par réplique (pause de 0,35 s), sous-titres calés sur l'audio réel de chaque
    réplique avec un style ASS par locuteur (Sub / Sub2)."""
    speakers = story.get("speakers", {})
    audio_dir = vo_dest.parent
    gap = audio_dir / "_gap.mp3"
    if not gap.exists():
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-t", "0.35", "-c:a", "libmp3lame", "-b:a", "128k", str(gap)],
                       check=True, capture_output=True)
    parts, events, styles, t = [], [], {}, 0.0
    for j, line in enumerate(scene["dialogue"]):
        lp = audio_dir / f"{vo_dest.stem}_l{j:02d}.mp3"
        if not lp.exists():
            vid = (speakers.get(line["speaker"]) or {}).get("voice_id") or ""
            if vid.startswith("A_REMPLACER"):
                vid = ""
            eleven_client.tts(line["text"], lp, voice_id=vid or None)
        dur = eleven_client.duration_of(lp)
        spk = line["speaker"]
        if spk not in styles:
            styles[spk] = "Sub" if len(styles) % 2 == 0 else "Sub2"
        events.append([round(t, 2), round(t + dur, 2), line["text"], styles[spk]])
        parts.append(lp)
        t += dur + 0.35
    lst = audio_dir / f"{vo_dest.stem}_list.txt"
    entries = []
    for k, p in enumerate(parts):
        entries.append(f"file '{p}'\n")
        if k < len(parts) - 1:
            entries.append(f"file '{gap}'\n")
    lst.write_text("".join(entries), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", str(vo_dest)],
                   check=True, capture_output=True)
    subs_dest.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")


def stage_render(state: dict, progress=lambda msg: None) -> dict:
    """Animation Grok + voix off + montage. C'est l'étape payante (~10-20 min)."""
    story = load_story(state["story_id"])
    job_dir = Path(state["job_dir"])

    animated_secs = sum(s["duration"] for s in story["scenes"] if not s.get("still"))
    if animated_secs > config.MAX_VIDEO_SECONDS_PER_JOB:
        raise RuntimeError(
            f"Garde-fou coût: {animated_secs}s d'animation demandées > "
            f"MAX_VIDEO_SECONDS_PER_JOB={config.MAX_VIDEO_SECONDS_PER_JOB}")

    scene_files = []
    for i, scene in enumerate(story["scenes"]):
        n = i + 1
        image = Path(state["scenes"][i]["image"])
        clip = job_dir / "clips" / f"clip_{n:02d}.mp4"
        # Un plan fixe avec dialogue = format « BD » : image cartoon + voix
        # ElevenLabs par personnage + sous-titres — jamais envoyé à Veo.
        use_veo = (bool(scene.get("dialogue")) and config.DIALOGUE_ENGINE == "veo"
                   and not scene.get("still"))

        if not clip.exists() and not (scene.get("dialogue") and scene.get("flap")):
            if scene.get("still"):
                progress(f"🎬 Scène {n}/{len(story['scenes'])} : écran fixe (zoom ffmpeg)")
                assemble.still_to_clip(image, scene["duration"], clip)
            elif use_veo:
                progress(f"🎬 Scène {n}/{len(story['scenes'])} : Veo (parole + lèvres synchro)…")
                veo_client.generate_video(image, _veo_prompt(story, scene),
                                          scene["duration"], clip)
            else:
                progress(f"🎬 Scène {n}/{len(story['scenes'])} : animation Grok…")
                xai_client.generate_video(image, scene["motion_prompt"],
                                          scene["duration"], clip)
            state["scenes"][i]["clip"] = str(clip)
            state_mod.save(state)

        built = job_dir / f"scene_{n:02d}_final.mp4"

        if scene.get("dialogue") and scene.get("flap"):
            # Format « cartoon qui parle » : bouche ouverte/fermée alternées
            # pendant la voix du personnage, plans larges et serrés alternés.
            closed = job_dir / "images" / f"scene_{n:02d}_closed.png"
            if not closed.exists():
                progress(f"🗣 Scène {n}/{len(story['scenes'])} : dessin bouche fermée…")
                descs = ". ".join(c["description"] for c in _cast(story, scene))
                xai_client.generate_image(
                    f"{story['style']}. {descs}. {scene['image_prompt']}. "
                    f"Redraw EXACTLY this same illustration — same character, same pose, "
                    f"same colors, same framing, same background — with only ONE change: "
                    f"the mouth completely closed (small neutral line). No text, no watermark.",
                    closed, reference_paths=[str(image)])
                # Garde-fou : si le dessin « bouche fermée » ne ressemble pas au
                # dessin d'origine (le modèle a divagué), on n'anime pas la bouche
                # plutôt que d'afficher une image étrangère.
                if _similarity(image, closed) < 0.50:
                    shutil.copy(image, closed)
            vo = job_dir / "audio" / f"vo_{n:02d}.mp3"
            subs_file = job_dir / "audio" / f"subs_{n:02d}.json"
            if not vo.exists():
                _build_dialogue_audio(story, scene, vo, subs_file)
                state["scenes"][i]["vo_audio"] = str(vo)
                state_mod.save(state)
            sub_events = (json.loads(subs_file.read_text(encoding="utf-8"))
                          if subs_file.exists() else None)
            if not built.exists():
                assemble.flap_clip(image, closed, vo, built,
                                   sub_events=sub_events, punch=(n % 2 == 0))
            scene_files.append(built)
            continue

        if use_veo:
            # Le clip Veo contient déjà voix + ambiance : mise au format +
            # sous-titres calés par transcription Whisper (texte = scénario).
            if not built.exists():
                try:
                    events = subtitles.dialogue_events(clip, scene)
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    progress(f"⚠️ Sous-titres indisponibles scène {n} ({str(e)[:80]})")
                    events = None
                assemble.conform_clip(clip, built, sub_events=events)
            scene_files.append(built)
            continue

        vo = job_dir / "audio" / f"vo_{n:02d}.mp3"
        subs_file = job_dir / "audio" / f"subs_{n:02d}.json"
        if not vo.exists():
            if scene.get("dialogue"):
                _build_dialogue_audio(story, scene, vo, subs_file)
            else:
                eleven_client.tts(scene["vo"], vo)
            state["scenes"][i]["vo_audio"] = str(vo)
            state_mod.save(state)
        sub_events = (json.loads(subs_file.read_text(encoding="utf-8"))
                      if subs_file.exists() else None)

        if not built.exists():
            # Pas de sous-titres sur l'écran de marque : son texte est déjà dessiné.
            sub_text = "" if scene.get("image_file") else scene.get("vo", "")
            assemble.build_scene(clip, vo, sub_text, built,
                                 min_duration=float(scene["duration"]),
                                 sub_events=sub_events)
        scene_files.append(built)

    progress("🎞 Montage final…")
    merged = assemble.concat_scenes(scene_files, job_dir / "merged.mp4")
    final = assemble.add_music(merged, job_dir / f"{state['job_id']}_FINAL.mp4")
    state["final_video"] = str(final)
    state["stage"] = "video_done"
    return state_mod.save(state)
