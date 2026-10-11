# Suivi vivant de GreatOS

> Vue générée depuis `learning/agent_sessions.jsonl`. Ne pas modifier manuellement : utilisez `scripts/log_agent_session.py`.

## État courant

- Aucune session marquée `in_progress`.

## Journal récent

### 2026-10-11T13:55:10.705322+00:00 — Copilot — completed

Évaluation du périmètre Docker pour une exécution reproductible de Jarvis sur plusieurs machines

**Décisions**
- Aucun élément signalé.

**Changements**
- Aucune modification produit; recommandation de containeriser d'abord l'API web headless et de garder audio, contrôle du bureau et intégrations Windows sur l'hôte

**Vérification**
- Lecture de README, requirements.txt, interface_morphique/server.py et scripts d'entrée; vérification de l'état Git existant

**Blocages**
- Aucun élément signalé.

**À suivre**
- Si validé, définir le périmètre de l'image API, ses volumes/configuration, et un docker-compose.yml avec healthcheck sans inclure .env ni données locales

### 2026-10-10T05:09:37.899823+00:00 — Buffy — completed

Audit complet : 517/518 tests verts, 1 echec lie a un test dependant de l'heure et des donnees reelles (pattern_analyzer), absence CI/linter, auth fail-open si JARVIS_API_KEY absente

**Décisions**
- Aucun élément signalé.

**Changements**
- aucune modification de code, rapport d'audit seul

**Vérification**
- pytest -q (1 failed, 517 passed, 1 skipped), py_compile des nouveaux fichiers, revue git/secrets/env

**Blocages**
- Aucun élément signalé.

**À suivre**
- Isoler le test pattern_anomaly (memoire factice), ajouter CI GitHub Actions + ruff, corriger le fail-open d'authentification du serveur morphique

### 2026-10-09T14:27:19.887878+00:00 — Antigravity — completed

Resolution du declenchement parasite : filtre wake-word local Vosk (<50ms) et seuil VAD rehausse a 650

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/wake_word_local.py (nouveau pre-filtre Vosk local), scripts/jarvis_live_daemon.py (integration du pre-filtre avant tout appel Groq, rehaussement seuil VAD de 300 a 650)

**Vérification**
- pytest 34/34 passed + import daemon OK

**Blocages**
- Aucun élément signalé.

**À suivre**
- Relancer lancer_jarvis.bat et tester : la TV ne declenchera plus rien, seul Jarvis activera l ecoute

### 2026-10-09T13:49:18.926081+00:00 — Antigravity — completed

Confirmation vocale native dans le demon temps reel : plus aucun input() clavier

**Décisions**
- Aucun élément signalé.

**Changements**
- datashield/confirmations.py (VoiceConfirmationHandler + use_voice_confirmation context manager), scripts/jarvis_live_daemon.py (boucle enveloppee dans use_voice_confirmation)

**Vérification**
- 34/34 tests au vert + import daemon OK

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester vocalement : dire une action sensible et repondre 'oui' ou 'non' a voix haute. Ensuite Lot 1 du chantier : exemptions natives dans la Trust Matrix

### 2026-10-09T13:31:21.881566+00:00 — Antigravity — completed

Cadrage formel du chantier dedie Autonomie et Gouvernance (Harmonisation DataShield, DEFCON et Trust Matrix)

**Décisions**
- Aucun élément signalé.

**Changements**
- Creation de CHANTIER_AUTONOMIE_GOUVERNANCE.md a la racine

**Vérification**
- Revue de code de trust_registry.py, policy.py, safety.py et trace d execution sur Carl/trust_matrix.json

**Blocages**
- Aucun élément signalé.

**À suivre**
- Executer le Lot 1 : exemption native des domaines READ/multimedia/vision dans trust_registry.py et promotion dans le profil de Carl

### 2026-10-09T13:00:25.357420+00:00 — Antigravity — completed

Suppression de la confirmation manuelle pour les actions multimedia et support des alias de volume (decrease, increase)

**Décisions**
- Aucun élément signalé.

**Changements**
- taskflow/tools.py (passage de controler_multimedia_tool a RiskLevel.READ sans confirmation terminal), context_engine/desktop_awareness.py (support des alias decrease/increase/baisse/monte et 5 crans de volume)

**Vérification**
- pytest tests/test_audio_capture.py tests/test_voice_input.py tests/test_voice_improvements.py tests/test_voice_output.py : 34/34 passed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester 'diminue le volume' et 'augmente le volume' sans confirmation.

### 2026-10-09T11:54:07.293414+00:00 — Antigravity — completed

Architecture hybride et fallback local souverain instantane (Groq Whisper <2s -> Vosk local, Edge-TTS <2.5s -> Piper local)

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_transcription.py (Groq avec max_retries=0 et timeout 2.0s sans retry bloquant), jarvis/voice_output_edge.py (timeout 2.5s et bascule automatique sur Piper local), jarvis/voice_input.py (fallback transparent sur Vosk direct), jarvis/voice_output.py (integration de la boucle hybride)

**Vérification**
- pytest tests/test_audio_capture.py tests/test_voice_input.py tests/test_voice_improvements.py tests/test_voice_output.py : 34/34 passed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester l interaction vocale complete avec simulation de deconnexion reseau.

### 2026-10-09T11:49:04.582607+00:00 — Antigravity — completed

Restauration du fallback audio strict d origine (Piper local + Vosk local + sounddevice) conformement a la demande utilisateur

**Décisions**
- Aucun élément signalé.

**Changements**
- Restauration complete de jarvis/voice_output.py, jarvis/voice_input.py, jarvis/audio_capture.py et tests/test_voice_input.py a l etat Git initial. Retrait des variables JARVIS_USE_EDGE_TTS et JARVIS_USE_GROQ_WHISPER de .env.

**Vérification**
- pytest tests/test_audio_capture.py tests/test_voice_input.py tests/test_voice_improvements.py tests/test_voice_output.py : 34/34 passed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Laisser l utilisateur tester la stack locale de production restauree.

### 2026-10-09T11:32:18.730638+00:00 — Antigravity — completed

Ajout du controle reel de Windows par Jarvis (Les Mains) : volume, medias, lancement d applications, minimisation de bureau et verrouillage

**Décisions**
- Aucun élément signalé.

**Changements**
- taskflow/windows_actions.py (controle volume user32, medias, lancement VS Code/terminal/explorateur, minimisation fenetres, verrouillage Windows), scripts/jarvis_live_daemon.py (routage vocal direct ultra-rapide des commandes systeme avec confirmation vocale)

**Vérification**
- pytest tests/test_audio_capture.py tests/test_voice_input.py tests/test_voice_improvements.py tests/test_voice_output.py : 34/34 passed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester les commandes Windows en direct dans la session de l utilisateur via lancer_jarvis.bat.

### 2026-10-09T11:05:16.275400+00:00 — Antigravity — completed

Ajout de la Vision d ecran en direct (Les Yeux de Jarvis) via Qwen 3.8 27B Vision sur Groq

**Décisions**
- Aucun élément signalé.

**Changements**
- core_intellect/screen_vision.py (capture ecran multi-moniteurs mss + PIL ImageGrab fallback et analyse Qwen 3.8 27B Vision sur Groq), scripts/jarvis_live_daemon.py (routage vocal automatique des intentions visuelles 'regarde mon ecran', 'cette erreur')

**Vérification**
- pytest tests/test_audio_capture.py tests/test_voice_input.py tests/test_voice_improvements.py tests/test_voice_output.py : 34/34 passed

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester l analyse visuelle live via lancer_jarvis.bat en demandant 'Jarvis, regarde mon ecran'.
