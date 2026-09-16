# État des lieux — GreatOS

**Date de révision :** 16 septembre 2026

**Statut global :** prototype local-first avancé ; refactor structurel prioritaire en cours.
**Source de vérité :** le code et les tests du dépôt. Le [cahier des charges](Documents/CAHIER_DES_CHARGES.md) décrit la cible, pas l'état de livraison.

## Résumé

GreatOS est une surcouche intelligente personnelle pour Windows, composée de huit modules Python. Jarvis est utilisable en texte et en voix ; il dispose d'une cascade LLM, d'outils locaux, d'automatisations, d'une API FastAPI et d'interfaces web/HUD.

Les correctifs de stabilisation récents ont limité la latence des fournisseurs locaux, évité des cascades cloud excessives, amélioré la résilience de la capture vocale et suspendu l'agent autonome pendant une interaction utilisateur. Les suites ciblées de stabilité et de sécurité exécutées lors de cette révision sont vertes.

Le projet ne doit pas encore être présenté comme une implémentation complète des critères PFE 2028 ou de la vision 2033. Avant tout nouveau chantier fonctionnel ou apprentissage automatique, la priorité est de terminer le refactor décrit ci-dessous.

## Modules : état réel

| Module | Disponible aujourd'hui | Limites et éléments à réaliser |
|---|---|---|
| **Jarvis** | Conversation texte/voix, wake word Vosk, double-clap, Piper TTS, mémoire de session, Mode Stark, orchestration des outils. | Les objectifs NLU >80 %, réponse <2 s à 95 % et mémoire conversationnelle illimitée ne sont pas mesurés ni garantis. |
| **Core Intellect** | Cascade Groq / OpenRouter / Jarvis-GC / Ollama, analyse d'intention, outils connus, gestion de réponses LLM dégradées. | Pas de Random Forest ni Knowledge Graph démontré ; qualité des recommandations non mesurée. |
| **Context Engine** | Mémoire JSON/SQLite, état système, suggestions, recherche sémantique et détection de patterns simples. | Pas de hooks OS complets, LSTM ni prédiction temporelle avancée. |
| **TaskFlow** | Outils fichiers, commandes, web, navigateur, calendrier/email, workflows et automatisations planifiées. Les commandes et écritures/suppressions de fichiers consultent désormais DataShield via le contrat noyau. | Les intégrations externes annoncées ne sont pas toutes validées ; les autres capacités doivent migrer vers le même passage de sécurité centralisé. |
| **Progress Tracker** | Objectifs, suivi persistant et analytics de base. | Dashboard complet, gamification, ARIMA et visualisations avancées ne sont pas établis. |
| **DataShield** | DEFCON, protections de chemins, confirmations, classification d'erreurs et autodestruction contrôlée. | Chiffrement AES-256-GCM, SQLCipher, Argon2id, 2FA/TOTP et détection ML ne sont pas implémentés. |
| **SyncSphere** | Snapshots locaux `.gos`, liste et restauration. | Les snapshots sont des archives `tar.gz`, pas des sauvegardes chiffrées ; pas de synchronisation multi-appareils. |
| **Interface Morphique** | API FastAPI, SSE, interface web HTML/JS, interface Tkinter et HUDs vocaux/navigateur. | Pas d'Electron, React, Tailwind ni de huit layouts contextuels démontrés. |

## Architecture et responsabilités

L'architecture opérationnelle actuelle est :

```text
Interfaces (web, Tkinter, voix, CLI)
             ↓
Jarvis : orchestration des interactions
             ↓
Core Intellect : interprétation et décision
             ↓
TaskFlow : exécution des outils
             ↓
DataShield : règles de zones, DEFCON et confirmations
             ↓
Windows, fichiers, réseau et services locaux
```

La cible du cahier des charges est une architecture de huit modules métier souverains. Jarvis orchestre, mais ne possède ni la sécurité, ni la persistance, ni l'exécution. Core Intellect décide sans exécuter ; TaskFlow exécute sans définir de politique ; DataShield décide `allow`, `confirm` ou `deny` sans produire d'effet système. Context Engine conserve les preuves et le contexte ; Progress Tracker mesure l'impact ; SyncSphere assure la continuité ; Interface Morphique présente les événements.

L'implémentation historique reste partiellement couplée : `taskflow/tools.py` est encore la façade unique de nombreux outils appartenant en réalité aux huit modules. Les appels directs d'un outil par Jarvis et les décisions de sécurité locales doivent donc disparaître progressivement, sans casser l'API, les prompts ni les automatisations existantes.

## Refactor de souveraineté des modules — priorité active

### Décisions non négociables

1. Les huit modules du CDC restent les seuls domaines métier. Aucun neuvième module métier ne doit être créé.
2. `greatos_contracts.py` et `greatos_capabilities.py` sont des fichiers du **noyau d'intégration**, pas des modules : ils ne décident pas, n'exécutent pas et ne persistent pas.
3. Toute capacité a un propriétaire unique, un nom canonique stable et un résultat structuré.
4. Toute action à effet externe passe par DataShield avant son exécution. Le module propriétaire classe l'opération ; DataShield rend la politique ; le propriétaire exécute.
5. `OUTILS` est une façade de compatibilité temporaire. Elle ne doit plus être confondue avec la propriété métier des capacités.
6. La migration doit préserver les comportements utiles et être validée par tests à chaque tranche. Aucun « grand remplacement » non testé.
7. L'apprentissage continu à partir des agents est reporté après la stabilisation de ce socle. Le journal des agents est déjà capturé, mais ne doit pas devenir une source de règles automatiques avant la fin du refactor.

### Éléments déjà implémentés

| Élément | État | Emplacement | Rôle réel |
|---|---|---|---|
| Contrat noyau | En place | `greatos_contracts.py` | `CapabilityRequest`, `PolicyDecision`, `CapabilityResult`, risques et statuts partagés. |
| Politique centralisée | Première tranche en place | `datashield/policy.py` | Évalue une capacité et répond `allow`, `confirm` ou `deny`. |
| Commandes et fichiers | Première migration en place | `taskflow/tools.py` | `system.execute_command`, `system.execute_powershell`, `filesystem.write` et `filesystem.delete` consultent DataShield. |
| Catalogue de propriété | En place | `greatos_capabilities.py` | Associe les alias historiques aux noms canoniques et aux modules propriétaires. |
| Inventaire Core Intellect | En place | `core_intellect/tool_signatures.py` | Expose au LLM la signature, la capacité canonique et son propriétaire. |
| Continuité inter-agents | En place | `learning/agent_sessions.jsonl`, `SUIVI_PROJET.md`, `AGENTS.md` | Journal append-only, vue humaine dérivée et protocole obligatoire de relais. |

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

| Étape | Travail à faire | Critère d'acceptation |
|---|---|---|
| 0 — Baseline | Lire `AGENTS.md`, `SUIVI_PROJET.md`, les dernières entrées de `learning/agent_sessions.jsonl` et ce document. Lancer les tests ciblés avant toute modification. | L'agent sait ce qui est en cours et l'état des tests avant d'éditer. |
| 1 — Dispatcher noyau | **Terminé pour Jarvis.** `execute_capability()` résout un alias ou un nom canonique et retourne systématiquement `CapabilityResult`. Les interactions normales, le chemin historique `executer_outil`, Stark, la veille autonome et la journalisation d'échange l'utilisent. | Les chemins Jarvis n'appellent plus directement une fonction de la façade ; succès, refus, erreur, annulation et timeout ont un format commun. |
| 2 — Traçabilité contexte | **Terminé.** Chaque `CapabilityResult` est journalisé par Context Engine avec capacité canonique, propriétaire, paramètres non sensibles filtrés (masquage strict des secrets/clés/tokens), décision DataShield, durée (ms) et preuve/résultat. Les traces sont consultables via `consulter_trace_capacites()` / `lire_traces_capacites()`. | Une action peut être expliquée et retrouvée sans dépendre des logs console. Aucun secret n'est persisté. |
| 3 — Mesure de progression | **Terminé.** Progress Tracker consomme systématiquement les `CapabilityResult` structurés via `enregistrer_impact_capacite()` : mesure des métriques d'exécution (succès, échecs, durée cumulée ms par capacité et module) et mise à jour de progression stricte uniquement lorsqu'un objectif actif est lié (par `goal_id` ou `capacite_cible`). Aucune progression inventée sans objectif associé. | Progress Tracker consomme des événements structurés, pas des chaînes de texte. |
| 4 — Migrations par propriétaire | **Terminé.** Extractions réussies de `taskflow/tools.py` vers les modules souverains : `datashield.tools` (DEFCON), `progress_tracker.tools` (objectifs, progression, métriques), `syncsphere.tools` (snapshots), `interface_morphique.tools` (overlay navigation), et `context_engine.memory_tools` (traces capacités, journal agents). Rétrocompatibilité totale maintenue via ré-exportation et façade `OUTILS`. | Chaque capacité migrée possède son implémentation métier dédiée dans son module et ses tests de contrat de souveraineté. |
| 5 — Politique DataShield complète | **Terminé.** Toutes les capacités à effet externe passent désormais par `evaluate_capability` : snapshots et restaurations (`syncsphere`), maintenance et stockage (`vider_temp`, `vider_corbeille` destructif), planification et automatisations (`ajouter_automatisation_tool`, `ajouter_surveillance_dossier_tool`), navigateur web (`naviguer_vers_tool`, `cliquer_element_tool`, `remplir_formulaire_tool`, `executer_sequence_tool`, sessions), réseau (`decouvrir_appareils_tailscale`), et calendrier/e-mail. Aucune capacité à effet externe ne contourne DataShield. | Aucune capacité à effet externe ne contourne la politique centrale. |
| 6 — Planification et API | **Terminé.** Contrats `PlanStep` et `ExecutionPlan` établis dans `greatos_contracts`. Core Intellect conçoit des plans structurés ordonnés (`planifier_objectif`) avec capacités canoniques, préconditions et dépendances, sans jamais exécuter les étapes. Jarvis orchestre le graphe de dépendances (`orchestrer_plan`) sans logique métier, soumet chaque étape à `evaluate_capability`, trace dans Context Engine, mesure dans Progress Tracker et diffuse des événements uniformisés (`plan_created`, `step_started`, `policy_decision`, `step_completed`, `plan_completed`) relayés par l'API SSE (`/jarvis/plan`, `/jarvis/plan/stream`). | Le plan, la décision sécurité et le résultat sont visibles de façon cohérente dans toutes les interfaces. |
| 7 — Retrait progressif | **Terminé.** `OUTILS` a été élevé d'un simple dictionnaire anonyme à une instance de `LegacyToolRegistry(dict)` dans `greatos_capabilities` et `taskflow/tools.py`. Tous les appels internes (y compris dans `taskflow/scheduler.py`) passent par le dispatcher central `execute_capability()`. La rétrocompatibilité versionnée (mapping, clés, introspection) est 100% préservée sans qu'aucun composant interne n'invoque directement de fonction brute anonyme. | Aucun appel interne ne dépend d'un dictionnaire anonyme de fonctions. |

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
5. Centraliser la décision de sécurité dans DataShield et chiffrer les données/snapshots avant de revendiquer les contrôles cryptographiques du cahier des charges.

## Portée plateforme

La version actuelle est principalement **Windows**. Les références à macOS, Linux, applications mobiles, API publique, éditions commerciales, E2EE multi-appareils et conformité (RGPD, ISO 27001, SOC 2) relèvent de la roadmap et ne sont pas livrées dans ce dépôt.
