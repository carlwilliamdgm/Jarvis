# Suivi vivant de GreatOS

> Vue générée depuis `learning/agent_sessions.jsonl`. Ne pas modifier manuellement : utilisez `scripts/log_agent_session.py`.

## État courant

- Aucune session marquée `in_progress`.

## Journal récent

### 2026-10-05T10:54:18.736236+00:00 — Senior Software Engineer — completed

Nettoyage integral et dynamisation : 482/482 tests au vert, restructuration docs/, scripts/ et runtime/, elimination des blocages tests vocaux

**Décisions**
- Aucun élément signalé.

**Changements**
- Racine assainie, service/ eclate vers modules proprietaires, docs/ unifiee, scripts/run.ps1 et healthcheck.py operationnels, runtime/ isole, test_voice_input/test_audio_capture/test_voice_reliability/test_phase4_hardening/test_desktop_vision repares

**Vérification**
- pytest complet : 482 passed, 1 skipped, 9 deselected, 0 failed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Terrain pret pour les futurs developpements sur une base 100% saine

### 2026-10-05T10:23:09.943455+00:00 — Antigravity - Nettoyage et Dynamisation GreatOS — completed

Nettoyage complet du projet : racine assainie, service/ réorganisé, docs/ centralisée, runtime/ isolé, tests corrigés, healthcheck et run.ps1 créés. 121/121 tests verts.

**Décisions**
- Aucun élément signalé.

**Changements**
- Étape 1: suppression .tmp, monitor.py->scripts/, install_web_search.py->bootstrap/, .gitignore étendu, .dist/ supprimé. Étape 2: windows_service.py archivé dans docs/archive/, proactive_daemon.py->jarvis/, consolidation_scheduler.py->context_engine/, imports corrigés dans agent.py et server.py. Étape 3: docs/ créé avec guides/, architecture/, archive/, 5 guides déplacés, cahier des charges déplacé. Étape 4: pytest.ini enrichi de 9 marqueurs par module. Étape 5: runtime/ créé, 4 fichiers JSON d'état déplacés dedans, 3 modules mis à jour. Étape 6: scripts/healthcheck.py et scripts/run.ps1 créés. Correction tests: test_voice_improvements (activation locale _ADAPTIVE_THRESHOLD_ENABLED), test_desktop_vision (marqueur @pytest.mark.integration pour capturer_ecran_live_structure).

**Vérification**
- 121/121 tests core passés après toutes les modifications. Healthcheck: systeme operationnel. 0 regression introduite.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Ajouter les marqueurs @pytest.mark.xxx dans les fichiers de tests existants pour filtrage par module. Configurer un CI GitHub Actions minimal (.github/workflows/ci.yml). Supprimer les dossiers Documents/ et Notes dev/ maintenant vides.

### 2026-10-05T10:18:32.985800+00:00 — Antigravity - Nettoyage GreatOS — completed

Nettoyage et dynamisation complets : racine assainie, service/ réorganisé, docs/ centralisée, runtime/ isolé, healthcheck et run.ps1 créés

**Décisions**
- Aucun élément signalé.

**Changements**
- Étapes 1-6 : suppression tmp, déplacement bootstrap/scripts, docs/guides, docs/architecture, docs/archive, runtime/, scripts/healthcheck.py, scripts/run.ps1, correction imports service->jarvis/context_engine, pytest.ini mis à jour

**Vérification**
- 105 tests passés avant et après toutes les modifications (suite core 7 fichiers)

**Blocages**
- Aucun élément signalé.

**À suivre**
- Ajouter les marqueurs pytest par module sur les fichiers de tests. Configurer un CI GitHub Actions minimal.

### 2026-10-04T20:50:27.670660+00:00 — Devin — completed

Adaptation du codebase pour installation sur machine vierge

**Décisions**
- Aucun élément signalé.

**Changements**
- update_scheduled_task.ps1 : remplacement des chemins absolus par $PSScriptRoot; scripts/audit/static_analysis.ps1 : utilisation de $PSScriptRoot pour déterminer le projet; scripts/audit/architecture_docs.ps1 : correction du chemin du projet; tests/manual/README.md : remplacement des chemins absolus par %USERPROFILE%; INSTALLATION_MACHINE_VIERGE.md : nouveau guide d'installation automatisée complet; README.md : ajout de référence au nouveau guide d'installation; ETAT_DES_LIEUX.md : ajout d'une section sur l'installation machine vierge et mise à jour du statut global

**Vérification**
- Vérification des chemins absolus via grep, lecture des scripts modifiés, création du nouveau guide d'installation, mise à jour de la documentation existante

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester le script d'installation sur une machine vierge pour valider le processus complet

### 2026-10-04T20:36:41.804535+00:00 — Devin — completed

Mise à jour de la documentation du projet

**Décisions**
- Aucun élément signalé.

**Changements**
- ETAT_DES_LIEUX.md : date de révision mise à jour au 4 octobre 2026, ajout d'une section détaillée sur les améliorations vocales récentes (validation secondaire wake word, VAD spectral, transcription robuste, réinitialisation TTS, latence optimisée, wake word statique), mise à jour de la description du module Jarvis pour refléter ces améliorations; SUIVI_PROJET.md régénéré automatiquement depuis learning/agent_sessions.jsonl

**Vérification**
- Lecture des fichiers de documentation existants, régénération de SUIVI_PROJET.md via render_project_status, écriture des modifications dans ETAT_DES_LIEUX.md

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider sur matériel réel les améliorations vocales décrites (faux positifs/négatifs, latence, bruit ambiant)

### 2026-10-02T11:44:32.719185+00:00 — Codex - Audit sortie vocale — completed

Évite qu'un signal d'arrêt TTS périmé coupe la réponse vocale suivante après une erreur de synthèse ou de démarrage audio.

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_output.py : réinitialisation de l'événement d'arrêt au début d'une nouvelle tentative et lors des erreurs de synthèse ou sd.play.

**Vérification**
- python -m py_compile jarvis/voice_output.py réussi; git diff --check ciblé réussi; tests non exécutés conformément à la demande.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider sur matériel réel la commande stop pendant lecture et le comportement après une erreur de synthèse ou de sortie audio.

### 2026-10-02T11:41:36.835445+00:00 — Codex - VAD bruit ambiant — completed

Correction localisée des débordements int16 et du reset incomplet dans AdaptiveVAD.

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/audio_capture.py: calcul des magnitudes float32 avant abs et remise à zéro de l'état, fenêtres de saturation et ZCR dans reset_floor.

**Vérification**
- Compilation python -m py_compile jarvis/audio_capture.py réussie; aucun test exécuté conformément à la consigne; modifications concurrentes préexistantes conservées.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider les transitions sur captures réelles incluant silence, parole faible et fort niveau, sans modifier les paramètres adaptatifs avant mesure.

### 2026-10-02T11:40:49.649434+00:00 — Codex - Fiabilite transcription — completed

Evite qu'une absence temporaire de trame audio soit injectee comme silence et coupe un segment Vosk.

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_input.py : _EngineStream signale les lectures vides comme discontinuite et renvoie un buffer vide; transcrire_flux ignore les buffers vides et remet le compteur a zero apres une lecture continue.

**Vérification**
- python -m py_compile jarvis/voice_input.py reussi; tests non executes comme demande. Revue du diff limitee au chemin transcrire_flux/_EngineStream; changement adaptatif wake word preexistant conserve sans modification.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider avec micro reel et une interruption ponctuelle de producteur que le segment Vosk reprend sans coupe; verifier le comportement apres trois lectures consecutives vides.

### 2026-10-02T11:39:25.906322+00:00 — Codex - Audit wake word — completed

Audit adaptation de seuil : désactivation de l'apprentissage non supervisé qui pouvait faire dériver le seuil

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_input.py : adaptation dynamique désactivée; seuil statique configurable conservé et intervalle de confirmation 250 ms préservé

**Vérification**
- py_compile jarvis/voice_input.py réussi; git diff --check ciblé exécuté; tests non exécutés conformément à la demande

**Blocages**
- Aucun élément signalé.

**À suivre**
- Prévoir une calibration locale fondée sur des retours explicites ou données étiquetées avant de réactiver une adaptation automatique

### 2026-10-02T11:29:57.390167+00:00 — Codex - Audit renforcement mode vocal — completed

Audit étendu du cycle vocal et correction d'un défaut de reconnexion pouvant créer deux threads lecteurs concurrents; confirmation wake-word espacée.

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/audio_capture.py : reconnexion du flux dans le thread capture propriétaire sans relancer un deuxième worker; jarvis/voice_input.py : espacement minimal des détections wake-word confirmées.

**Vérification**
- py_compile réussi sur audio_capture.py et voice_input.py; tests non exécutés. git diff --check remonte des espaces finaux dans les modifications vocales préexistantes des deux fichiers.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider le reconnect micro en conditions réelles et mesurer le délai de confirmation wake-word avec différents niveaux de bruit.
