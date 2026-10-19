# Agent vidéo Nour Meet — installation sur ton VPS

Pipeline automatisé : histoire → images (Grok Imagine) → **validation Telegram** →
animation 720p (Grok) → voix off FR (ElevenLabs) → montage + sous-titres (ffmpeg) →
**validation Telegram** → vidéo prête à publier. Une vidéo tous les 2 jours (cron).

## 1. Les 3 clés à créer (~10 min)

1. **xAI** : https://console.x.ai → crée un compte, ajoute du crédit (10-20 $ pour commencer),
   puis *API Keys* → copie la clé `xai-...`
2. **ElevenLabs** : https://elevenlabs.io → plan Starter (5 $/mois) → *Profile → API Keys*.
   Puis va dans *Voices*, choisis une voix française qui te plaît (écoute les previews),
   et copie son **Voice ID**.
3. **Telegram** : parle à `@BotFather` → `/newbot` → suis les étapes → copie le token.

## 2. Installation (~10 min)

```bash
# En SSH sur ton VPS :
sudo apt update && sudo apt install -y ffmpeg python3-venv
sudo mkdir -p /opt/nour-video-agent && sudo chown $USER /opt/nour-video-agent
# Copie l'archive sur le VPS (depuis ton ordi : scp nour-video-agent.tar.gz user@vps:/tmp/)
tar xzf /tmp/nour-video-agent.tar.gz -C /opt/nour-video-agent --strip-components=1
cd /opt/nour-video-agent
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # colle tes 3 clés + le Voice ID
```

## 3. Premier test SANS dépenser (mode à blanc)

```bash
cd /opt/nour-video-agent
sed -i 's/DRY_RUN=0/DRY_RUN=1/' .env
venv/bin/python bot.py &
# Sur Telegram : envoie /start à ton bot (il enregistre ton chat_id), puis /nouvelle
# Tu dois recevoir : le script, 9 images factices, les boutons ✅/❌,
# puis après ✅ une vidéo factice de ~1min15 avec sous-titres. Si oui, tout marche.
kill %1
sed -i 's/DRY_RUN=1/DRY_RUN=0/' .env   # repasse en mode réel
```

## 4. Lancement en service (tourne tout seul)

```bash
sudo cp systemd/nour-video-agent.service /etc/systemd/system/
sudo nano /etc/systemd/system/nour-video-agent.service   # remplace TON_UTILISATEUR par ton user SSH
sudo systemctl daemon-reload
sudo systemctl enable --now nour-video-agent
sudo systemctl status nour-video-agent   # doit être "active (running)"
```

## 5. La cadence "une vidéo tous les 2 jours"

```bash
crontab -e
# Ajoute (tous les 2 jours à 9h00) :
0 9 */2 * * cd /opt/nour-video-agent && venv/bin/python enqueue.py >> data/cron.log 2>&1
```

Tu peux aussi lancer une vidéo à la main à tout moment avec `/nouvelle` sur Telegram.

## 6. Utilisation au quotidien (tout se passe sur Telegram)

- **Checkpoint 1** : tu reçois le script + les 9 images (~0,50 $ dépensés).
  `/regen 3` refait l'image 3, `/regen 3 plus sombre` avec une consigne.
  ✅ lance l'étape payante (~9-10 $ en 720p), ❌ annule.
- **Checkpoint 2** : tu reçois la vidéo finale. ✅ = validée (le fichier est dans
  `data/jobs/<job>/..._FINAL.mp4` sur le VPS, et déjà dans Telegram → *Enregistrer la vidéo*
  sur ton téléphone pour la publier sur TikTok/Insta).
- `/status` : où en est le job. `/retry` : relance après une erreur (reprend où ça s'était
  arrêté, sans repayer ce qui est déjà généré).

## 7. Musique de fond (optionnel mais recommandé)

Dépose un MP3 libre de droits dans `assets/music/` sur le VPS — il sera mixé
automatiquement à bas volume avec fondu de fin. (Banques gratuites : Pixabay Music,
YouTube Audio Library. Évite les musiques du commerce : les pubs de marque ne sont pas
couvertes par les licences des sons "tendance" des plateformes.)

## 8. Ajouter les prochaines histoires

Chaque vidéo = un fichier JSON dans `stories/` (regarde `01-karim.json` : voix off,
prompt d'image, prompt d'animation et durée par scène). L'agent produit les histoires
dans l'ordre des noms de fichiers et coche celles déjà faites (`data/history.json`).
Demande-moi les 9 suivantes quand la vidéo test te convient.

## Budget attendu (720p, 15 vidéos/mois)

~62 s d'animation par vidéo (le CTA final est un zoom ffmpeg gratuit) ≈ 8,70 $ + ~0,60 $
d'images ≈ **9-10 $ la vidéo**, soit ~140-160 $/mois avec les regénérations, + 5 $
ElevenLabs. Le garde-fou `MAX_VIDEO_SECONDS_PER_JOB` bloque tout job qui dépasserait
110 s d'animation.
