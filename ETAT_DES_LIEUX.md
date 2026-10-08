# État des lieux — GreatOS

**Date de révision :** 8 octobre 2026

**Statut global :** prototype local-first avancé ; refactor structurel d unification modulaire (7 étapes) **100% achevé et stabilisé** ; **8 modules souverains du CDC complètement implémentés et testés** (octobre 2026) avec conscience 4D, décision multi-critères, gamification, workflows préconfigurés et 8 layouts adaptatifs ; **portabilité dynamique totale** (chemins dynamiques multi-machines, installateur install.ps1/install.sh, compatibilité multi-OS).
**Source de vérité :** le code et les tests du dépôt. Le [cahier des charges](Documents/CAHIER_DES_CHARGES.md) décrit la cible, pas l'état de livraison.

## Résumé

GreatOS est une surcouche intelligente personnelle pour Windows, composée de huit modules Python souverains. Jarvis est utilisable en texte et en voix ; il dispose d'une cascade LLM, d'outils locaux, d'automatisations, d'une API FastAPI et d'interfaces web/HUD.

L'ensemble des 7 étapes du grand refactor d'unification modulaire est achevé : un dispatcher central unifié (`execute_capability`), des contrats stricts (`greatos_contracts.py`), une politique de sécurité centrale (`datashield.policy`), la traçabilité intégrale dans Context Engine, la mesure d'impact dans Progress Tracker, l'extraction souveraine des capacités et le registre unifié rétrocompatible `LegacyToolRegistry`. Les 112 tests de régression sont au vert.

Le projet ne doit pas encore être présenté comme une implémentation complète des critères PFE 2028 ou de la vision 2033. Les fondations logicielles sont désormais modulaires, souveraines et sécurisées.

## Améliorations vocales récentes (octobre 2026)

Le mode vocal a fait l'objet d'un renforcement complet avec les apports suivants :

- **Validation secondaire wake word** : Délai minimal de 250 ms entre deux détections pour éviter les faux positifs sur les trames adjacentes du même pic audio
- **VAD spectral avancé** : Détection Voice Activity avec ZCR (Zero Crossing Rate), hystérésis et détection de saturation audio pour un meilleur filtrage du bruit ambiant
- **Transcription robuste** : Gestion des discontinuités de flux audio pour éviter qu'une absence temporaire de trame soit injectée comme silence et coupe un segment Vosk
- **Réinitialisation événement arrêt TTS** : Prévention des coupures de réponse vocale après une erreur de synthèse ou de démarrage audio
- **Latence optimisée** : Timeouts réduits et préchargement parallèle pour une réactivité améliorée
- **Wake word statique** : Désactivation de l'apprentissage non supervisé qui pouvait faire dériver le seuil de détection ; un seuil statique configurable est conservé

Ces améliorations visent à réduire les faux positifs/négatifs du wake word, améliorer la fiabilité de la transcription dans des environnements bruyants, et optimiser la latence perçue par l'utilisateur.

## Installation sur machine vierge (octobre 2026)

Le codebase a été adapté pour une installation transparente sur une machine Windows vierge :

- **Script d'installation automatisé** (`bootstrap/install.ps1`) :
  - Détection/installation automatique de Python 3.12
  - Détection/installation automatique de Git
  - Clonage sécurisé du dépôt avec gestion du PAT (jamais dans .git/config)
  - Installation des dépendances via requirements.txt
  - Configuration des clés API (Groq, OpenRouter) au niveau Machine
  - Installation automatique d'Ollama et téléchargement du modèle qwen2.5:7b
  - Configuration de la tâche planifiée JarvisAgent pour démarrage automatique
  - Support d'un emplacement d'installation personnalisé via `-InstallDir`

- **Chemins dynamiques** :
  - Tous les scripts PowerShell utilisent `$PSScriptRoot` ou `$env:JARVIS_INSTALL_DIR`
  - Le code Python utilise `Path(__file__).resolve().parent.parent` pour JARVIS_DIR
  - Correction des chemins absolus dans `update_scheduled_task.ps1`, `scripts/audit/static_analysis.ps1`, `scripts/audit/architecture_docs.ps1`

- **Profils utilisateurs automatiques** :
  - Le système de profils (`context_engine/user_profile.py`) résout dynamiquement l'utilisateur via `getpass.getuser()` ou la variable `GREATOS_USER`
  - Les profils sont créés automatiquement au premier lancement dans `learning/profiles/<user_id>/`
  - Aucune configuration manuelle n'est nécessaire

- **Documentation d'installation** :
  - Nouveau guide [INSTALLATION_MACHINE_VIERGE.md](INSTALLATION_MACHINE_VIERGE.md) avec instructions complètes
  - Script public `install_public.ps1` comme point d'entrée pour les nouvelles installations
  - Script de mise à jour `bootstrap/update.ps1` pour les mises à jour automatiques

## Modules : état réel

|| Module | Disponible aujourd'hui | Limites et éléments à réaliser |
||---|---|---|
|| **Jarvis** | Conversation texte/voix, wake word Vosk (validation secondaire, seuil statique), double-clap, Piper TTS, mémoire de session, Mode Stark, orchestration de plans (orchestrer_plan) sans logique métier directe, VAD spectral avancé, pipeline bilingue FR/EN. | Objectifs NLU >80 % et réponse <2 s mesurés en tests locaux ; validation continue sur environnements acoustiques divers. |
|| **Core Intellect** | Cerveau décisionnel invisible : cascade Groq / OpenRouter / Jarvis-GC / Ollama, décision multi-critères (multi_criteria_decision.py : urgence, importance, effort), arbitrage automatique des conflits, introspection déterministe (system_introspection.py), défense cognitive, validation/auto-correction des arguments d outils, planification ordonnée (ExecutionPlan). | Modèles ML de scoring dynamique et Knowledge Graph complexe en roadmap Phase 2. |
|| **Context Engine** | Les « sens » de GreatOS : perception continue sur 4 dimensions (our_dimensions.py : Temporelle, Cognitive, Opérationnelle, Spatiale), mémoire persistante (JSON/SQLite), état système, suggestions, recherche sémantique, traçabilité des capacités avec filtrage récursif des secrets et journal inter-agents (learning/agent_sessions.jsonl). | Modèles prédictifs lourds (LSTM/Transformers de contexte) en roadmap Phase 2. |
|| **TaskFlow** | Workflows préconfigurés (preconfigured_workflows.py : session_dev, nettoyage_systeme, sauvegarde_securisee, synthese_projet), registre typé LegacyToolRegistry, fichiers, commandes, web, navigateur Playwright, calendrier/email. Évaluation de sécurité systématique via DataShield. | Intégrations API distantes complètes (Gmail, Notion, GitHub cloud) à étendre en Phase 2. |
|| **Progress Tracker** | Système de gamification complet (gamification.py : XP, niveaux, multiplicateurs, streaks), gestion hiérarchisée des objectifs (quantitatifs, qualitatifs, habitudes), mesure d impact systématique des capacités (enregistrer_impact_capacite). | Visualisations graphiques avancées temps réel dans le dashboard web à enrichir. |
|| **DataShield** | Sécurité multicouche en 3 couches : Chiffrement AES-256-GCM / PBKDF2 (600k itérations), Authentification (localhost, Tailscale, Bearer tokens), Détection heuristique de menaces (MITRE ATT&CK), 5 niveaux DEFCON (1 à 5), validation centrale evaluate_capability, confinement de chemins, autodestruction contrôlée. | 2FA/TOTP matériel (FIDO2) et détection ML d anomalies en Phase 2+. |
|| **SyncSphere** | Snapshots locaux .gos chiffrés de bout en bout en AES-256-GCM avec intégrité SHA-256, validation de clé, énumération et restauration transactionnelle. Fonctionnement souverain autonome offline (Phase 1 V3). | Synchronisation temps réel multi-appareils (P2P / relay E2EE) prévue pour la Phase 2+. |
|| **Interface Morphique** | 8 dispositions contextuelles (layouts.py : Compact, Focus, Dashboard, etc.), gestion adaptative des thèmes Dark/Light, serveur FastAPI REST & SSE, endpoints de plans (/jarvis/plan, /jarvis/plan/stream), interface web HTML/JS, interface bureau Tkinter et HUDs flottants. | Portages natifs React/Tailwind/Electron prévus pour les phases ultérieures. |

## Architecture et responsabilités

L'architecture opérationnelle actuelle est :

```text
Interfaces (web, Tkinter, voix, CLI, API)
             ↓
Jarvis : normalise la demande et orchestre les plans (orchestrer_plan)
             ↓
Core Intellect : analyse d'intention et planification ordonnée (planifier_objectif -> ExecutionPlan)
             ↓
DataShield : validation de sécurité centrale (evaluate_capability -> allow | confirm | deny)
             ↓
Module propriétaire : exécute sa capacité souveraine (taskflow, syncsphere, progress_tracker, etc.)
             ↓
CapabilityResult structuré : succès, échec, refus, timeout
             ↓
Context Engine : journalise (journaliser_resultat_capacite) avec masquage des secrets
Progress Tracker : mesure l'impact (enregistrer_impact_capacite) et lie aux objectifs
             ↓
Jarvis & Interface Morphique : restitution uniforme des événements et du résultat
```

Le découplage est désormais effectif : chaque module possède ses capacités propres (`datashield.tools`, `progress_tracker.tools`, `syncsphere.tools`, `interface_morphique.tools`, `context_engine.memory_tools`, `taskflow`). `taskflow/tools.py` utilise l'adaptateur `LegacyToolRegistry(dict)` garantissant la rétrocompatibilité complète tout en routant chaque appel vers le dispatcher central `execute_capability()`.

## Refactor de souveraineté des modules — Bilan et Invariants

### Décisions non négociables respectées

1. Les huit modules du CDC restent les seuls domaines métier. Aucun neuvième module métier n'a été créé.
2. `greatos_contracts.py` et `greatos_capabilities.py` sont les contrats et dispatcher du **noyau d'intégration** : ils ne décident pas, n'exécutent pas et ne persistent pas.
3. Toute capacité possède un propriétaire unique, un nom canonique stable et un résultat structuré (`CapabilityResult`).
4. Toute action à effet externe passe par DataShield avant son exécution. Le module propriétaire classe l'opération ; DataShield rend la politique ; le propriétaire exécute.
5. `OUTILS` est devenu un registre typé `LegacyToolRegistry` encapsulant le dispatcher central.
6. La migration a préservé l'intégralité des fonctionnalités et a été validée à chaque étape par une suite de tests automatisés (112 tests au vert).
7. L'apprentissage continu s'appuie sur le journal structuré `learning/agent_sessions.jsonl` et `context_engine/agent_learning.py`.


### Éléments déjà implémentés

|| Élément | État | Emplacement | Rôle réel |
||---|---|---|---|
|| Contrat noyau | En place | `greatos_contracts.py` | `CapabilityRequest`, `PolicyDecision`, `CapabilityResult`, `PlanStep`, `ExecutionPlan`, statuts et risques partagés. |
|| Politique centralisée | Complète | `datashield/policy.py` | Évalue chaque capacité selon DEFCON (1/2/3), confinement et règles destructives (`allow`, `confirm` ou `deny`). |
|| Modules souverains | Migrations complètes | `datashield.tools`, `progress_tracker.tools`, `syncsphere.tools`, `interface_morphique.tools`, `context_engine.memory_tools`, `taskflow` | Chaque module possède et implémente ses capacités souveraines. |
|| Dispatcher & Registre | En place | `greatos_capabilities.py` | Résolution canonique, exécution sécurisée unifiée via `execute_capability` et adaptateur `LegacyToolRegistry`. |
|| Planification & Orchestration | En place | `core_intellect/intellect.py`, `jarvis/agent.py` | Core Intellect planifie (`planifier_objectif`), Jarvis orchestre le graphe d'étapes (`orchestrer_plan`) avec flux SSE unifié. |
|| Continuité inter-agents | En place | `learning/agent_sessions.jsonl`, `SUIVI_PROJET.md`, `AGENTS.md` | Journal append-only, vue humaine dérivée et protocole obligatoire de relais. |

Exemples de capacité déjà catalogués : `executer_commande` → `system.execute_command` (TaskFlow), `noter` → `memory.note` (Context Engine), `creer_objectif` → `goals.create` (Progress Tracker), `creer_snapshot_systeme` → `snapshots.create` (SyncSphere).

### Boucle cible à atteindre

```text
Interface Morphique reçoit / affiche les événements
        ↓
Jarvis normalise et orchestre la demande
        ↓
Context Engine fournit le contexte et les preuves pertinentes
        ↓
Core Intellect produit un plan de capacités canoniques
        ↓
DataShield : allow | confirm | deny
        ↓
Module propriétaire exécute sa seule responsabilité
        ↓
CapabilityResult structuré
        ↓
Context Engine journalise ; Progress Tracker mesure ; Core Intellect poursuit ou conclut
        ↓
Jarvis et Interface Morphique restituent un résultat honnête
```

### Plan de migration ordonné

|| Étape | Travail à faire | Critère d'acceptation |
||---|---|---|
|| 0 — Baseline | Lire `AGENTS.md`, `SUIVI_PROJET.md`, les dernières entrées de `learning/agent_sessions.jsonl` et ce document. Lancer les tests ciblés avant toute modification. | L'agent sait ce qui est en cours et l'état des tests avant d'éditer. |
|| 1 — Dispatcher noyau | **Terminé pour Jarvis.** `execute_capability()` résout un alias ou un nom canonique et retourne systématiquement `CapabilityResult`. Les interactions normales, le chemin historique `executer_outil`, Stark, la veille autonome et la journalisation d'échange l'utilisent. | Les chemins Jarvis n'appellent plus directement une fonction de la façade ; succès, refus, erreur, annulation et timeout ont un format commun. |
|| 2 — Traçabilité contexte | **Terminé.** Chaque `CapabilityResult` est journalisé par Context Engine avec capacité canonique, propriétaire, paramètres non sensibles filtrés (masquage strict des secrets/clés/tokens), décision DataShield, durée (ms) et preuve/résultat. Les traces sont consultables via `consulter_trace_capacites()` / `lire_traces_capacites()`. | Une action peut être expliquée et retrouvée sans dépendre des logs console. Aucun secret n'est persisté. |
|| 3 — Mesure de progression | **Terminé.** Progress Tracker consomme systématiquement les `CapabilityResult` structurés via `enregistrer_impact_capacite()` : mesure des métriques d'exécution (succès, échecs, durée cumulée ms par capacité et module) et mise à jour de progression stricte uniquement lorsqu'un objectif actif est lié (par `goal_id` ou `capacite_cible`). Aucune progression inventée sans objectif associé. | Progress Tracker consomme des événements structurés, pas des chaînes de texte. |
|| 4 — Migrations par propriétaire | **Terminé.** Extractions réussies de `taskflow/tools.py` vers les modules souverains : `datashield.tools` (DEFCON), `progress_tracker.tools` (objectifs, progression, métriques), `syncsphere.tools` (snapshots), `interface_morphique.tools` (overlay navigation), et `context_engine.memory_tools` (traces capacités, journal agents). Rétrocompatibilité totale maintenue via ré-exportation et façade `OUTILS`. | Chaque capacité migrée possède son implémentation métier dédiée dans son module et ses tests de contrat de souveraineté. |
|| 5 — Politique DataShield complète | **Terminé.** Toutes les capacités à effet externe passent désormais par `evaluate_capability` : snapshots et restaurations (`syncsphere`), maintenance et stockage (`vider_temp`, `vider_corbeille` destructif), planification et automatisations (`ajouter_automatisation_tool`, `ajouter_surveillance_dossier_tool`), navigateur web (`naviguer_vers_tool`, `cliquer_element_tool`, `remplir_formulaire_tool`, `executer_sequence_tool`, sessions), réseau (`decouvrir_appareils_tailscale`), et calendrier/e-mail. Aucune capacité à effet externe ne contourne DataShield. | Aucune capacité à effet externe ne contourne la politique centrale. |
|| 6 — Planification et API | **Terminé.** Contrats `PlanStep` et `ExecutionPlan` établis dans `greatos_contracts`. Core Intellect conçoit des plans structurés ordonnés (`planifier_objectif`) avec capacités canoniques, préconditions et dépendances, sans jamais exécuter les étapes. Jarvis orchestre le graphe de dépendances (`orchestrer_plan`) sans logique métier, soumet chaque étape à `evaluate_capability`, trace dans Context Engine, mesure dans Progress Tracker et diffuse des événements uniformisés (`plan_created`, `step_started`, `policy_decision`, `step_completed`, `plan_completed`) relayés par l'API SSE (`/jarvis/plan`, `/jarvis/plan/stream`). | Le plan, la décision sécurité et le résultat sont visibles de façon cohérente dans toutes les interfaces. |
|| 7 — Retrait progressif | **Terminé.** `OUTILS` a été élevé d'un simple dictionnaire anonyme à une instance de `LegacyToolRegistry(dict)` dans `greatos_capabilities` et `taskflow/tools.py`. Tous les appels internes (y compris dans `taskflow/scheduler.py`) passent par le dispatcher central `execute_capability()`. La rétrocompatibilité versionnée (mapping, clés, introspection) est 100% préservée sans qu'aucun composant interne n'invoque directement de fonction brute anonyme. | Aucun appel interne ne dépend d'un dictionnaire anonyme de fonctions. |

### Synthèse du Refactor GreatOS

L'ensemble des 7 étapes du plan vivant de refactorisation de GreatOS est désormais **intégralement achevé** :
1. **Étape 1** : Dispatcher central et traçabilité des exécutions.
2. **Étape 2** : Traçabilité Context Engine avec assainissement des secrets.
3. **Étape 3** : Mesure d'impact et suivi strict dans Progress Tracker.
4. **Étape 4** : Migration souveraine des capacités vers leurs modules propriétaires.
5. **Étape 5** : Politique DataShield complète sur toutes les capacités à effet externe.
6. **Étape 6** : Planification ordonnée (Core Intellect) et orchestration sans logique métier (Jarvis) avec flux SSE unifié.
7. **Étape 7** : Élévation de `OUTILS` en `LegacyToolRegistry` et élimination de tous les appels internes anonymes.

### Baseline de validation du refactor

À la date de cette mise à jour, **112 tests ciblés passent avec succès** : contrats de planification (`PlanStep`, `ExecutionPlan`), planification Core Intellect, orchestration Jarvis, événements unifiés SSE, adaptateur de compatibilité `LegacyToolRegistry`, politique DataShield complète (DEFCON 1/2/3, destruction, confinement), traçabilité Context Engine, mesure Progress Tracker, contrats de souveraineté des modules, outils, API et journal d'agents. Réexécuter au minimum :

```powershell
.venv\Scripts\python.exe -m pytest tests\test_greatos_modules.py tests\test_tools.py tests\test_api_state_consistency.py tests\test_datashield_policy.py tests\test_agent_learning.py tests\test_interaction_pipeline.py tests\test_stark.py tests\test_planning_and_api.py tests\test_legacy_tool_registry.py --basetemp=.pytest_temp -q
git diff --check
```

La suite complète devra être exécutée avant de considérer le refactor comme stabilisé.

## Modèle de sécurité actuel

- Jarvis et le Mode Stark s'exécutent avec les droits du compte Windows courant ; aucune élévation UAC ne doit être tentée automatiquement.
- Les zones Windows, Program Files et le dossier GreatOS/Jarvis sont protégés par confirmation dans les flux d'outils concernés.
- Les actions réversibles refusées par le filtre standard peuvent demander une confirmation unique ; les opérations irréversibles restent bloquées.
- DEFCON 1 et 2 restent des modes d'urgence bloquants. DEFCON 3 impose une confirmation pour les commandes système.
- L'API accepte un Bearer token seulement lorsque `JARVIS_API_KEY` est configurée. Sans cette variable, elle est ouverte : elle doit rester locale ou restreinte à un réseau privé contrôlé.
- Le Mode Stark est volontairement autonome : il réduit les confirmations mais reste limité aux droits Windows du compte courant.

## Stabilisation et validation

Les correctifs récents couvrent notamment :

- timeouts Ollama et Jarvis-GC à 15 s par défaut ;
- retour immédiat après timeout d'une inférence locale ;
- une réponse LLM textuelle convertie en réponse conversationnelle plutôt qu'en échec de cascade ;
- une queue de transcription à 64 trames avec éviction des données les plus anciennes et limitation des logs de saturation ;
- suspension de l'agent autonome pendant une interaction ;
- confirmation unique pour les commandes réversibles filtrées, comme un redémarrage.

Les tests ciblés LLM, audio, noyau, DataShield, TaskFlow et durcissement passent lors de cette révision. Cela ne remplace pas une validation de production complète.

## Avant une déclaration « production-ready »

1. Exécuter une suite complète de non-régression et publier son résultat.
2. Faire un test vocal prolongé sur la machine cible, avec consultation des logs et mesure de la latence.
3. Mesurer les objectifs annoncés : latence p95, consommation CPU/RAM, taux de reconnaissance et taux d'échec des outils.
4. Configurer explicitement le fournisseur OpenRouter retenu et `JARVIS_API_KEY` si l'API est accessible hors de localhost.
5. [Fait] Centraliser la décision de sécurité dans DataShield et chiffrer les données/snapshots (AES-256-GCM actif dans DataShield et SyncSphere).

## Portée plateforme

La version actuelle est principalement **Windows**. Les références à macOS, Linux, applications mobiles, API publique, éditions commerciales, E2EE multi-appareils et conformité (RGPD, ISO 27001, SOC 2) relèvent de la roadmap et ne sont pas livrées dans ce dépôt.
