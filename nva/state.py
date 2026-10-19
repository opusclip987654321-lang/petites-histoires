"""État du job courant (un seul job à la fois, persistant sur disque).

Étapes: queued -> images_done (checkpoint 1) -> approved_1 -> rendering
        -> video_done (checkpoint 2) -> published | rejected
"""
import json
import time
from . import config


def load():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return None


def save(state):
    state["updated_at"] = int(time.time())
    config.STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state


def new_job(story: dict):
    job_id = f"{story['id']}-{time.strftime('%Y%m%d-%H%M%S')}"
    job_dir = config.JOBS_DIR / job_id
    (job_dir / "images").mkdir(parents=True, exist_ok=True)
    (job_dir / "clips").mkdir(parents=True, exist_ok=True)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)
    state = {
        "job_id": job_id,
        "story_id": story["id"],
        "stage": "queued",
        "job_dir": str(job_dir),
        "scenes": [
            {"idx": i, "image": None, "clip": None, "vo_audio": None}
            for i in range(len(story["scenes"]))
        ],
        "final_video": None,
        "error": None,
    }
    return save(state)


def clear():
    if config.STATE_FILE.exists():
        config.STATE_FILE.unlink()
