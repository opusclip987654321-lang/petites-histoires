"""Montage ffmpeg : canevas 1080x1920, upscale lanczos + netteté,
sous-titres incrustés nets, voix off par scène, musique de fond optionnelle."""
import subprocess
import textwrap
from pathlib import Path

from . import config
from .eleven_client import duration_of

FPS = 24
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Sub,Arial,64,&H00FFFFFF,&H00000000,&H80000000,-1,4,1,2,60,60,340
Style: Sub2,Arial,64,&H003AA3F2,&H00000000,&H80000000,-1,4,1,2,60,60,340

[Events]
Format: Layer, Start, End, Style, Text
"""
# Sub2 = safran (&H003AA3F2 est BGR pour #F2A33A) : couleur du 2e locuteur en mode dialogue.


def _run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg a échoué:\n{' '.join(args)}\n{p.stderr[-2000:]}")


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _scene_ass(text: str, total: float, dest: Path) -> Path:
    """Découpe la voix off en sous-titres courts répartis sur la durée de la scène."""
    chunks = []
    for sentence in text.replace("…", "...").split(". "):
        sentence = sentence.strip().rstrip(".")
        if sentence:
            chunks.extend(textwrap.wrap(sentence, width=34) and
                          ["\\N".join(textwrap.wrap(sentence, width=34)[:2])] or [])
    if not chunks:
        chunks = [text[:60]]
    per = total / len(chunks)
    lines = [ASS_HEADER]
    for i, chunk in enumerate(chunks):
        lines.append(f"Dialogue: 0,{_ts(i * per)},{_ts(min((i + 1) * per, total))},Sub,{chunk}\n")
    dest.write_text("".join(lines), encoding="utf-8")
    return dest


def _events_ass(events, dest: Path) -> Path:
    """Sous-titres depuis des événements précis [(start, end, text, style)] —
    mode dialogue : chaque réplique est calée sur son audio réel."""
    lines = [ASS_HEADER]
    for start, end, text, style in events:
        wrapped = "\\N".join(textwrap.wrap(text, width=34)[:2])
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},{style},{wrapped}\n")
    dest.write_text("".join(lines), encoding="utf-8")
    return dest


def build_scene(clip: Path, vo: Path, text: str, dest: Path, min_duration: float = 3.0,
                sub_events=None) -> Path:
    """Un fichier mp4 normalisé par scène (1080x1920, h264+aac, sous-titres incrustés)."""
    vo_len = duration_of(vo)
    target = max(vo_len + 0.7, min_duration)
    # Les sous-titres suivent la voix (vo_len), pas la durée totale de la scène,
    # sinon ils se désynchronisent pendant le silence de fin.
    if sub_events:
        ass = _events_ass(sub_events, dest.with_suffix(".ass"))
    else:
        ass = _scene_ass(text, vo_len + 0.3, dest.with_suffix(".ass"))
    ass_path = str(ass).replace("'", r"\'").replace(":", r"\:")
    vf = (
        f"scale={config.OUT_W}:{config.OUT_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={config.OUT_W}:{config.OUT_H},unsharp=5:5:0.6:5:5:0.0,fps={FPS},"
        f"tpad=stop_mode=clone:stop_duration=10,ass='{ass_path}'"
    )
    _run([
        "ffmpeg", "-y", "-i", str(clip), "-i", str(vo),
        "-filter_complex",
        f"[0:v]{vf}[v];[1:a]aresample=44100,apad[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{target:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        "-pix_fmt", "yuv420p", str(dest),
    ])
    return dest


def _speech_end(clip: Path) -> float | None:
    """Détecte un long silence en FIN de clip (Veo anime les lèvres même quand
    la réplique est finie) : renvoie l'instant où couper, ou None."""
    p = subprocess.run(
        ["ffmpeg", "-i", str(clip), "-af", "silencedetect=noise=-35dB:d=0.5",
         "-f", "null", "-"], capture_output=True, text=True)
    total = duration_of(clip)
    starts, ends = [], []
    for line in p.stderr.splitlines():
        if "silence_start:" in line:
            starts.append(float(line.split("silence_start:")[1].strip()))
        elif "silence_end:" in line:
            ends.append(float(line.split("silence_end:")[1].split("|")[0].strip()))
    if not starts:
        return None
    last = starts[-1]
    # silence qui court jusqu'à la fin du clip : soit aucun silence_end après
    # lui, soit un silence_end collé à la fin du fichier (EOF)
    tail = (len(ends) < len(starts) or ends[-1] < last
            or ends[-1] >= total - 0.3)
    if tail and last > 1.5 and total - last > 0.8:
        return round(last + 0.4, 2)
    return None


def conform_clip(clip: Path, dest: Path, sub_events=None) -> Path:
    """Normalise un clip qui contient DÉJÀ sa bande-son (Veo : voix + ambiance) :
    - coupe la queue muette (lèvres qui bougent sans son en fin de plan) ;
    - égalise le volume (loudnorm) pour des raccords doux entre scènes ;
    - micro-fondus audio aux bords (anti-clic au collage) ;
    - incruste les sous-titres [(start, end, texte, style)] si fournis ;
    - met au format du montage final (1080x1920, h264+aac, 24 fps)."""
    cut = _speech_end(clip)
    end = cut if cut else duration_of(clip)
    vf = (
        f"scale={config.OUT_W}:{config.OUT_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={config.OUT_W}:{config.OUT_H},unsharp=5:5:0.6:5:5:0.0,fps={FPS}"
    )
    if sub_events:
        ass = _events_ass(sub_events, dest.with_suffix(".ass"))
        ass_path = str(ass).replace("'", r"\'").replace(":", r"\:")
        vf += f",ass='{ass_path}'"
    af = (f"aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11,"
          f"afade=t=in:d=0.04,afade=t=out:st={max(end - 0.08, 0):.2f}:d=0.08")
    cmd = ["ffmpeg", "-y", "-i", str(clip)]
    if cut:
        cmd += ["-t", f"{cut:.2f}"]
    cmd += [
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
        "-pix_fmt", "yuv420p", str(dest),
    ]
    _run(cmd)
    return dest


def flap_clip(open_img: Path, closed_img: Path, vo: Path, dest: Path,
              sub_events=None, punch: bool = False) -> Path:
    """Animation « bouche qui parle » à l'ancienne : deux dessins (bouche
    ouverte / fermée) alternés rapidement pendant la voix, bouche fermée
    ensuite. punch=True cadre serré (coup de zoom) pour varier les plans."""
    vo_len = duration_of(vo)
    frame = 0.14  # durée de chaque état de bouche
    entries, t, open_state = [], 0.0, True
    while t < vo_len:
        img = open_img if open_state else closed_img
        entries.append(f"file '{img}'\nduration {frame}\n")
        t += frame
        open_state = not open_state
    entries.append(f"file '{closed_img}'\nduration 0.45\n")
    entries.append(f"file '{closed_img}'\n")  # dernière image répétée (exigence concat)
    lst = dest.with_suffix(".frames.txt")
    lst.write_text("".join(entries), encoding="utf-8")

    if punch:  # plan serré : zoom ~1.2 centré sur le haut (le visage)
        zw, zh = int(config.OUT_W * 1.22), int(config.OUT_H * 1.22)
        framing = (f"scale={zw}:{zh}:force_original_aspect_ratio=increase:flags=lanczos,"
                   f"crop={config.OUT_W}:{config.OUT_H}:(iw-{config.OUT_W})/2:(ih-{config.OUT_H})*0.22")
    else:
        framing = (f"scale={config.OUT_W}:{config.OUT_H}:force_original_aspect_ratio=increase:"
                   f"flags=lanczos,crop={config.OUT_W}:{config.OUT_H}")
    vf = f"{framing},unsharp=5:5:0.5:5:5:0.0,fps={FPS}"
    if sub_events:
        ass = _events_ass(sub_events, dest.with_suffix(".ass"))
        ass_path = str(ass).replace("'", r"\'").replace(":", r"\:")
        vf += f",ass='{ass_path}'"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-i", str(vo),
        "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=44100,apad[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{vo_len + 0.45:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        "-pix_fmt", "yuv420p", str(dest),
    ])
    return dest


def still_to_clip(image: Path, duration: int, dest: Path) -> Path:
    """Écran fixe animé par un lent zoom (zoompan) — pour le CTA final, gratuit."""
    frames = duration * FPS
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", str(duration),
        "-vf",
        f"scale={config.OUT_W * 2}:{config.OUT_H * 2}:"
        f"force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={config.OUT_W * 2}:{config.OUT_H * 2},"
        f"zoompan=z='min(zoom+0.0006,1.08)':d={frames}:x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':s={config.OUT_W}x{config.OUT_H}:fps={FPS}",
        "-pix_fmt", "yuv420p", str(dest),
    ])
    return dest


def concat_scenes(scene_files, dest: Path) -> Path:
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{f}'\n" for f in scene_files), encoding="utf-8")
    # Ré-encodage au concat : la copie directe accumule un léger décalage
    # audio/vidéo à chaque jonction (padding AAC), audible en fin de vidéo.
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
          "-pix_fmt", "yuv420p", "-vsync", "cfr", "-r", str(FPS), str(dest)])
    return dest


def add_music(video: Path, dest: Path) -> Path:
    """Mixe la première musique trouvée dans assets/music/ (volume bas, fade out)."""
    tracks = sorted(list(config.MUSIC_DIR.glob("*.mp3")) +
                    list(config.MUSIC_DIR.glob("*.m4a")) +
                    list(config.MUSIC_DIR.glob("*.wav")))
    if not tracks:
        video.replace(dest)
        return dest
    total = duration_of(video)
    _run([
        "ffmpeg", "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(tracks[0]),
        "-filter_complex",
        f"[1:a]volume=0.14,afade=t=out:st={total - 2.5:.2f}:d=2.5[m];"
        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", str(dest),
    ])
    return dest
