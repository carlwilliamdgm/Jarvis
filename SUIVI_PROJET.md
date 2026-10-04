# Suivi vivant de GreatOS

> Vue générée depuis `learning/agent_sessions.jsonl`. Ne pas modifier manuellement : utilisez `scripts/log_agent_session.py`.

## État courant

- Aucune session marquée `in_progress`.

## Journal récent

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

### 2026-10-02T11:25:43.853501+00:00 — Codex - Renforcement mode vocal — completed

Confirmation du mot de réveil espacée pour ignorer les trames adjacentes du même pic audio.

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_input.py : délai minimal de 250 ms entre deux détections comptées pour la confirmation secondaire.

**Vérification**
- py_compile jarvis/voice_input.py réussi; git diff --check ciblé réussi; tests non exécutés.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Valider le compromis latence/faux positifs en conditions réelles et ajuster le délai minimal si nécessaire.

### 2026-10-02T10:29:23.097744+00:00 — Devin — completed

Renforcement avancé du mode vocal : validation secondaire wake word, VAD spectral, transcription robuste, latence optimisée

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_input.py (validation secondaire wake word, timeouts réduits, préchargement parallèle), jarvis/audio_capture.py (VAD avec ZCR et détection saturation), jarvis/voice_output.py (garde anti-écho réduite), jarvis/voice_state.py (docs timeout 25s), tests/test_voice_reliability.py (nouveau fichier de tests)

**Vérification**
- Compilation Python réussie (py_compile) sur les 3 fichiers modifiés

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester en conditions réelles avec bruit ambiant pour valider le ZCR et la réduction des faux positifs. Surveiller les logs pour confirmer l'adaptation du seuil wake word et les confirmations multiples.

### 2026-10-02T10:18:31.817070+00:00 — Devin — completed

Renforcement du mode vocal : seuil adaptatif, VAD amélioré, reconnexion auto, latence optimisée

**Décisions**
- Aucun élément signalé.

**Changements**
- jarvis/voice_input.py (seuil adaptatif dynamique), jarvis/audio_capture.py (VAD avec hystérésis, reconnexion auto), tests/test_voice_improvements.py (nouveau fichier de tests)

**Vérification**
- 11 tests unitaires tous passés

**Blocages**
- Aucun élément signalé.

**À suivre**
- Tester les améliorations en conditions réelles pour valider l'impact sur les faux positifs/négatifs et la latence perçue

### 2026-10-01T19:16:56.951141+00:00 — Codex - Synthèse politique de permissions GreatOS — completed

Documentation de l'ensemble de la session : objectif OS standard, espaces protégés, rôle de la trust matrix, état actuel et suites.

**Décisions**
- Aucun élément signalé.

**Changements**
- Ajout d'un bilan daté dans EXECUTION_OUTILS.md séparant politique cible discutée, constats vérifiés et tâches à faire; aucune modification du comportement produit.

**Vérification**
- Lecture des consignes AGENTS.md et des docs de sécurité; inspection de datashield/policy.py, datashield/defcon.py, datashield/safety.py, datashield/threat_analyzer.py, context_engine/trust_registry.py et jarvis/agent.py; git diff --check.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Arbitrer le seuil de confiance et le comportement exact dans les espaces protégés; implémenter l'alignement des décisions de politique puis faire un essai quotidien contrôlé incluant une demande d'élévation OS.

### 2026-10-01T18:19:10.810654+00:00 — Codex - Audit politique de sécurité — completed

Cartographie de la politique DataShield appliquée aux capacités et identification des limites du flux.

**Décisions**
- Aucun élément signalé.

**Changements**
- Aucun changement produit; lecture de datashield/policy.py, datashield/defcon.py, datashield/safety.py, datashield/threat_analyzer.py, taskflow/tools.py et jarvis/agent.py.

**Vérification**
- Inspection statique des décisions ALLOW/CONFIRM/DENY et des points d'appel; aucun test exécuté.

**Blocages**
- Aucun élément signalé.

**À suivre**
- Si une correction est demandée, faire un audit ciblé des capacités destructives pouvant devenir silencieuses via la trust matrix, du chemin provenance EXTERNAL et de la définition attendue de DEFCON4.
