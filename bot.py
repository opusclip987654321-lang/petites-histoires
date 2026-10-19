"""Bot Telegram + moteur du pipeline. Tourne en continu sur le VPS (systemd).

Flux : enqueue.py (cron) crée un job "queued"
  -> le bot génère les images et t'envoie le CHECKPOINT 1 (script + 9 images)
  -> ✅ lance l'animation Grok + voix off + montage (l'étape payante)
  -> le bot t'envoie la vidéo finale : CHECKPOINT 2
  -> ✅ la vidéo est marquée prête à publier (fichier conservé dans data/jobs/)

Commandes : /start /status /nouvelle /regen <n° de scène> [consigne]
"""
import asyncio
import logging
import subprocess
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)

from nva import config, pipeline, publisher, state as state_mod, story_gen

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nva")

BUSY = asyncio.Lock()
CHAT_ID_FILE = config.DATA_DIR / "chat_id.txt"


def chat_id():
    if config.TELEGRAM_CHAT_ID:
        return config.TELEGRAM_CHAT_ID
    if CHAT_ID_FILE.exists():
        return CHAT_ID_FILE.read_text().strip()
    return None


# ------------------------------ Commandes ------------------------------

async def cmd_start(update: Update, _):
    CHAT_ID_FILE.write_text(str(update.effective_chat.id))
    await update.message.reply_text(
        f"✅ Agent vidéo Nour Meet connecté.\nTon chat_id : {update.effective_chat.id} "
        f"(enregistré automatiquement).\n\nCommandes : /status, /nouvelle, /regen <scène> [consigne]")


async def cmd_status(update: Update, _):
    st = state_mod.load()
    if not st:
        await update.message.reply_text("Aucun job en cours. /nouvelle pour en lancer un.")
    else:
        await update.message.reply_text(
            f"Job : {st['job_id']}\nÉtape : {st['stage']}"
            + (f"\nErreur : {st['error']}" if st.get("error") else ""))


async def cmd_nouvelle(update: Update, _):
    st = state_mod.load()
    if st and st["stage"] not in ("published", "rejected"):
        await update.message.reply_text(
            f"Un job est déjà en cours ({st['stage']}). Termine-le ou ❌ d'abord.")
        return
    story = pipeline.next_story()
    if not story:
        await update.message.reply_text(
            "🧠 Banque vide — j'invente une nouvelle histoire (charte éditoriale)…")
        try:
            story = await asyncio.to_thread(story_gen.generate_story)
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"⚠️ Génération impossible : {str(e)[:300]}")
            return
    state_mod.new_job(story)
    await update.message.reply_text(f"🚀 Nouveau job : {story['title']}")


async def cmd_regen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = state_mod.load()
    if not st or st["stage"] != "images_done":
        await update.message.reply_text("Regénération possible uniquement au checkpoint images.")
        return
    if not context.args:
        await update.message.reply_text("Usage : /regen 3  (ou /regen 3 plus sombre, sans sourire)")
        return
    n = int(context.args[0])
    note = " ".join(context.args[1:])
    await update.message.reply_text(f"🔄 Je regénère l'image de la scène {n}…")
    async with BUSY:
        st = await asyncio.to_thread(pipeline.regen_image, st, n, note)
    with open(st["scenes"][n - 1]["image"], "rb") as f:
        await update.message.reply_photo(f, caption=f"Scène {n} (nouvelle version)")
    await update.message.reply_text("Valide quand tout te va 👇", reply_markup=kb_checkpoint1())


# ------------------------------ Checkpoints ------------------------------

def kb_checkpoint1():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Lancer l'animation", callback_data="approve1"),
        InlineKeyboardButton("❌ Annuler ce job", callback_data="reject"),
    ]])


def kb_checkpoint2():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Valider (prête à publier)", callback_data="approve2"),
        InlineKeyboardButton("❌ Refuser", callback_data="reject"),
    ]])


async def send_checkpoint1(app, st):
    story = pipeline.load_story(st["story_id"])
    cid = chat_id()
    def scene_text(s):
        if s.get("dialogue"):
            return " — ".join(f"{d['speaker'].capitalize()} : « {d['text']} »"
                              for d in s["dialogue"])
        return s.get("vo", "")
    script = "\n\n".join(
        f"Scène {i + 1} ({s['duration']}s) : {scene_text(s)}"
        for i, s in enumerate(story["scenes"]))
    await app.bot.send_message(cid, f"📋 CHECKPOINT 1 — {story['title']}\n\n{script}")
    media = [InputMediaPhoto(open(sc["image"], "rb"), caption=f"Scène {i + 1}")
             for i, sc in enumerate(st["scenes"])]
    for batch_start in range(0, len(media), 10):
        await app.bot.send_media_group(cid, media[batch_start:batch_start + 10])
    await app.bot.send_message(
        cid, "Les images te vont ?\n🔄 /regen <scène> [consigne] pour en refaire une.\n"
             "✅ lance l'étape payante (animation + voix + montage).",
        reply_markup=kb_checkpoint1())


TELEGRAM_MAX = 45 * 1024 * 1024  # marge sous la limite de 50 Mo des bots


def _telegram_copy(final: Path) -> Path:
    """Telegram refuse les vidéos > 50 Mo : on envoie une copie compressée,
    l'original pleine qualité reste dans data/jobs/."""
    if final.stat().st_size <= TELEGRAM_MAX:
        return final
    tg = final.with_name(final.stem + "_TG.mp4")
    if not tg.exists() or tg.stat().st_size == 0:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(final),
            "-c:v", "libx264", "-preset", "medium", "-crf", "25",
            "-maxrate", "4M", "-bufsize", "8M",
            "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", str(tg),
        ], check=True, capture_output=True)
    return tg


async def send_checkpoint2(app, st):
    cid = chat_id()
    await app.bot.send_message(
        cid, "🎬 CHECKPOINT 2 — vidéo finale prête !\n"
             "🎲 Une scène a une diction ratée ? /reclip <n°> la regénère seule (~1,2 $).")
    send_path = await asyncio.to_thread(_telegram_copy, Path(st["final_video"]))
    with open(send_path, "rb") as f:
        await app.bot.send_video(cid, f, supports_streaming=True,
                                 width=1080, height=1920,
                                 read_timeout=300, write_timeout=300)
    await app.bot.send_message(cid, "Elle te va ?", reply_markup=kb_checkpoint2())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = state_mod.load()
    if not st:
        await q.edit_message_text("Aucun job en cours.")
        return
    if q.data == "approve1" and st["stage"] == "images_done":
        st["stage"] = "approved_1"
        state_mod.save(st)
        await q.edit_message_text("✅ Validé. Animation en cours (~10-20 min), je reviens vers toi…")
    elif q.data == "approve2" and st["stage"] == "video_done":
        pipeline.mark_done(st["story_id"])
        st["stage"] = "published"
        state_mod.save(st)
        final_video, story_id = st["final_video"], st["story_id"]
        await q.edit_message_text(
            f"✅ Vidéo validée ! Fichier : {Path(final_video).name}\n"
            f"(dans data/jobs/ sur le VPS)")
        state_mod.clear()
        if config.AUTO_PUBLISH and config.META_ACCESS_TOKEN:
            await context.bot.send_message(chat_id(), "📤 Publication Instagram + Facebook en cours…")
            story = pipeline.load_story(story_id)
            try:
                results = await asyncio.to_thread(publisher.publish_all, final_video, story)
                report = "\n".join(f"• {k} : {v}" for k, v in results.items())
                await context.bot.send_message(chat_id(), f"📣 Publication terminée :\n{report}")
            except Exception as e:  # noqa: BLE001
                log.exception("Erreur publication")
                await context.bot.send_message(
                    chat_id(), f"⚠️ Publication échouée : {str(e)[:400]}\n"
                               f"La vidéo reste dans Telegram, tu peux publier à la main.")
    elif q.data == "reject":
        st["stage"] = "rejected"
        state_mod.save(st)
        state_mod.clear()
        await q.edit_message_text("❌ Job annulé. /nouvelle pour repartir.")


# ------------------------------ Moteur ------------------------------

async def tick(context: ContextTypes.DEFAULT_TYPE):
    """Vérifie l'état toutes les 20 s et fait avancer le pipeline."""
    if BUSY.locked() or not chat_id():
        return
    st = state_mod.load()
    if not st or st.get("error"):
        return
    app = context.application
    try:
        if st["stage"] == "queued":
            async with BUSY:
                await app.bot.send_message(chat_id(), "🖼 Génération des images en cours…")
                st = await asyncio.to_thread(pipeline.stage_images, st)
                await send_checkpoint1(app, st)
        elif st["stage"] == "approved_1":
            async with BUSY:
                st["stage"] = "rendering"
                state_mod.save(st)

                def progress(msg):
                    asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id(), msg), loop)
                loop = asyncio.get_running_loop()
                st = await asyncio.to_thread(pipeline.stage_render, st, progress)
                await send_checkpoint2(app, st)
    except Exception as e:  # noqa: BLE001
        log.exception("Erreur pipeline")
        st = state_mod.load() or st
        st["error"] = str(e)[:500]
        state_mod.save(st)
        await app.bot.send_message(
            chat_id(), f"⚠️ Erreur : {str(e)[:500]}\n"
                       f"Corrige puis renvoie /retry (ou ❌ le job avec /status).")


async def cmd_reclip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Regénère le clip d'UNE scène (diction Veo ratée, geste bizarre…) puis
    refait le montage. Les autres scènes restent en cache. Utilisable au
    checkpoint 2, avant validation."""
    st = state_mod.load()
    if not st or st["stage"] != "video_done":
        await update.message.reply_text("Utilisable seulement au checkpoint 2 (vidéo prête, pas encore validée).")
        return
    if not context.args:
        await update.message.reply_text("Usage : /reclip 5  (regénère la scène 5)")
        return
    n = int(context.args[0])
    job_dir = Path(st["job_dir"])
    for f in [job_dir / "clips" / f"clip_{n:02d}.mp4",
              job_dir / f"scene_{n:02d}_final.mp4",
              job_dir / "merged.mp4",
              *job_dir.glob("*_FINAL.mp4"), *job_dir.glob("*_FINAL_TG.mp4")]:
        f.unlink(missing_ok=True)
    st["stage"] = "approved_1"
    st["error"] = None
    state_mod.save(st)
    await update.message.reply_text(
        f"🎲 Scène {n} rejouée (~1,2 $). Nouveau montage dans quelques minutes…")


async def cmd_publier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Publie (ou republie) la dernière vidéo finale sur Instagram + Facebook.
    Utile quand la publication auto a échoué (token Meta expiré, etc.)."""
    finals = sorted(config.JOBS_DIR.glob("*/*_FINAL.mp4"), key=lambda p: p.stat().st_mtime)
    if not finals:
        await update.message.reply_text("Aucune vidéo finale trouvée dans data/jobs/.")
        return
    final = finals[-1]
    job_name = final.parent.name
    story_id = next((f.stem for f in config.STORIES_DIR.glob("*.json")
                     if job_name.startswith(f.stem + "-")), None)
    if not story_id:
        await update.message.reply_text(f"Histoire introuvable pour le job {job_name}.")
        return
    (config.DATA_DIR / "meta_ids.json").unlink(missing_ok=True)  # cache token pages périmé
    await update.message.reply_text(f"📤 Publication de {final.name}…")
    story = pipeline.load_story(story_id)
    try:
        results = await asyncio.to_thread(publisher.publish_all, str(final), story)
        report = "\n".join(f"• {k} : {v}" for k, v in results.items())
        await update.message.reply_text(f"📣 Publication terminée :\n{report}")
    except Exception as e:  # noqa: BLE001
        log.exception("Erreur publication manuelle")
        await update.message.reply_text(f"⚠️ Publication échouée : {str(e)[:400]}")


async def cmd_retry(update: Update, _):
    st = state_mod.load()
    if st and st.get("error"):
        st["error"] = None
        if st["stage"] == "rendering":
            st["stage"] = "approved_1"  # reprend là où ça s'est arrêté (fichiers déjà faits gardés)
        state_mod.save(st)
        await update.message.reply_text("🔁 On retente…")
    else:
        await update.message.reply_text("Rien à retenter.")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN manquant dans .env")
    # Auto-reprise : un job tué en plein rendu (redémarrage, crash) reste à
    # l'étape "rendering" sans erreur -> on le remet en file, le rendu
    # reprendra là où il s'était arrêté (les fichiers déjà faits sont gardés).
    st = state_mod.load()
    if st and st.get("stage") == "rendering":
        st["stage"] = "approved_1"
        st["error"] = None
        state_mod.save(st)
        log.info("Job %s interrompu en plein rendu -> reprise automatique", st["job_id"])
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("nouvelle", cmd_nouvelle))
    app.add_handler(CommandHandler("regen", cmd_regen))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("reclip", cmd_reclip))
    app.add_handler(CommandHandler("publier", cmd_publier))
    app.add_handler(CallbackQueryHandler(on_button))
    app.job_queue.run_repeating(tick, interval=20, first=5)
    log.info("Agent vidéo Nour Meet démarré (DRY_RUN=%s)", config.DRY_RUN)
    app.run_polling()


if __name__ == "__main__":
    main()
