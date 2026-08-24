# Architecture Jarvis

Jarvis est un agent IA local-first en Python. Le composant qui raisonne est `core/intellect.py`; le reste du système orchestre, sécurise, persiste ou exécute. `memory.json` porte le contexte long terme, tandis que l'historique de conversation reste volontairement limité.

## Points d'entree

- `jarvis.py` : interface console, boucle principale, commandes de mode, orchestration des actions, mode Stark et agent autonome de veille.
- `jarvis.cmd` : lancement Windows.
- `monitor.py` : compatibilite pour lancer uniquement la surveillance stockage.
- `api/server.py` : point d'entree serveur FastAPI local, API REST, SSE et fichiers web statiques.
- `gui/app.py` : interface graphique Tkinter, cliente du flux SSE.
- `gui/web/index.html` : interface web autonome servie par `/web`.
- `JarvisAgent` : tâche planifiée Windows qui lance `uvicorn api.server:app` dans la session utilisateur.

## Flux principal

1. La console appelle directement `executer_interaction_utilisateur()`; Tkinter et le web l'appellent via l'API.
2. Cette fonction applique la même préparation de message, appelle `executer_agent()` et journalise l'échange.
3. `detecter_commande_mode()` intercepte les commandes (`!a`, `!S <objectif>`, activation/desactivation du mode action).
4. Hors commande spéciale, `parler()` appelle `core.intellect.interpreter_objectif()`.
5. Core Intellect renvoie une structure normalisee : objectif, type, actions et reponse naturelle.
6. `jarvis.py` execute les actions listées via `tools.OUTILS`, puis assemble la reponse finale.

Le modèle ne doit pas être appelé directement depuis les capabilities. Si une fonctionnalité doit "penser", elle remonte au Core Intellect ou reste une execution deterministe.

## Core

- `core/intellect.py` : cerveau unique de Jarvis. Construit le prompt d'interpretation, appelle les modeles, parse le JSON de decision et filtre les outils inconnus.
- `core/prompt.py` : prompts systeme historiques et prompts d'action/conversation utilises par certaines surfaces.
- `core/tool_signatures.py` : inventaire dynamique des capacites exposees. Il introspecte `tools.OUTILS` au moment de construire les prompts et l'outil `lire_capacites()`.
- `core/memory.py` : lecture/ecriture de `memory.json`, normalisation, journal d'actions, journal conversationnel et taches.
- `core/paths.py` : chemins racine (`JARVIS_DIR`, `MEMORY_PATH`) et informations OS.
- `core/safety.py` : validation des chemins, cartographie des zones protegees, confirmations ciblees et flag runtime du mode Stark.
- `core/translator.py` : traducteur d'intentions/patterns consultable via outils.
- `core/stark_parser.py` : parseur de la grammaire Stark (`>>`, `&&`, `||`).
- `core/stark_session.py` : coordination multi-instance Stark via `stark_actif.json`.

### Nouveaux modules Core

- `core/voice_state.py` : Gestion de l'etat vocal global (IDLE, LISTENING, THINKING, SPEAKING, ERROR) avec communication via fichier JSON partage `voice_state.json` pour l'overlay.
- `core/voice_overlay.py` : Overlay visuel flottant Tkinter affichant l'etat vocal en temps reel avec style HUD (fenetre sans bordure, topmost, positionnement configurable, polling a 100ms).
- `core/autodestruct.py` : Auto-destruction complete de Jarvis (service Windows, taches planifiees, variables d'environnement, modele Ollama, dossier Jarvis).
- `core/contextual_suggestions.py` : Generation de suggestions intelligentes basees sur les patterns comportementaux, l'etat systeme, l'heure actuelle, le contexte utilisateur et les automatisations potentielles.
- `core/decision_analyzer.py` : Auto-reflexion sur les decisions recentes, detection de patterns d'erreur recurrents, memorisation des solutions reussies pour reutilisation future.
- `core/error_classification.py` : Classification mecanique des erreurs systeme avec categories predefinies (acces_refuse, cible_introuvable, erreur_technique_outil, ressource_systeme_insuffisante, action_refusee_par_confirmation, autre).
- `core/pattern_analyzer.py` : Detection et analyse des patterns comportementaux (horaires d'utilisation, actions repetitives, sequences d'actions courantes, frequence globale).
- `core/semantic_search.py` : Indexation et recherche semantique dans l'historique des interactions avec extraction de mots-cles, detection de thematiques et analyse de connexions contextuelles.
- `core/system_monitor.py` : Surveillance continue de l'etat systeme (CPU, memoire, disque, reseau, processus) avec detection d'anomalies, enregistrement historique et analyse de tendances.
- `core/personality.py` : Gestion et adaptation de la personnalite Jarvis avec traits ajustables (sarcasme, formalite, proactivite, humour, empathie, concision, creativite) et evolution automatique basee sur les interactions.
- `core/confirmations.py` : Gestion des confirmations utilisateur avec historique et patterns de refus/acceptation.

## Mode Stark

Le mode Stark est active par `!S <objectif>` et vit dans `jarvis.py`.

- `core/stark_session.py` detecte les autres instances Stark actives avec PID + nom de process, nettoie les entrees mortes et n'interrompt jamais Stark en cas de fichier corrompu.
- `core/stark_parser.py` transforme l'objectif brut en segments executables.
- La grammaire explicite est :
  - `>>` : macro-etapes sequentielles, arret de la chaine si une etape echoue.
  - `&&` : dependances gauche-droite dans un segment.
  - `||` : alternatives/replis, premiere reussite retenue.
- Chaque micro-objectif a un budget local de `MAX_ETAPES_PAR_MICRO_OBJECTIF = 5`.
- Le prompt Stark donne au LLM uniquement le micro-objectif courant et le resume compact des tentatives de ce micro-objectif.
- Deux tentatives consecutives identiques declenchent une detection de pietinement.
- Le rapport final liste chaque macro-etape avec son statut : reussi, echoue ou jamais tente.

## Capabilities

Les modules `capabilities/` executent les actions concrètes. Ils ne decident pas de la strategie globale.

- `capabilities/files.py` : fichiers et dossiers.
- `capabilities/storage.py` : stockage, temp, corbeille, notifications et fichiers lourds.
- `capabilities/commands.py` : commandes shell et PowerShell.
- `capabilities/organization.py` : analyse et rangement de dossiers.
- `capabilities/memory_tools.py` : notes, preferences et contexte personnel.
- `capabilities/scheduler.py` : rappels et automatisations.
- `capabilities/custom_commands.py` : commandes personnalisees.
- `capabilities/watchers.py` : surveillance proactive de dossiers.
- `capabilities/voice_input.py` : reconnaissance vocale via Vosk avec wake word "Hey Jarvis" et double-clap.
- `capabilities/voice_output.py` : synthese vocale (TTS) via Piper avec modeles francais et anglais.
- `capabilities/clap_input.py` : detection de double-clap pour activation vocale alternative.
- `capabilities/calendar_integration.py` : integration avec calendrier (en developpement).
- `capabilities/email_integration.py` : integration avec email (en developpement).

## Facade outils

`tools.py` expose le registre `OUTILS`. C'est la facade stable appelee par `jarvis.py` et par Core Intellect pour valider les noms d'outils.

Responsabilites principales :

- adapter les signatures publiques des outils;
- appliquer les confirmations d'ecriture via `confirmer_ecriture_si_requise()`;
- court-circuiter les confirmations quand Stark est actif;
- journaliser certaines actions composees;
- fournir `bilan_proactif()`, `terminer_tache()`, `lire_capacites()` et les outils de consultation du traducteur.

## Conscience des capacites

Jarvis ne depend plus d'une liste statique pour savoir ce qu'il peut faire. L'inventaire des outils est genere en temps reel depuis `tools.OUTILS` par `core/tool_signatures.py`.

Ce mecanisme alimente deux surfaces :

- les prompts de decision (`core/intellect.py` et `core/prompt.py`);
- l'outil public `lire_capacites()`, que Jarvis peut appeler lorsqu'on lui demande ce qu'il sait faire.

Consequence pratique : ajouter une capability ne suffit toujours pas. Il faut l'exposer dans `tools.OUTILS`, mais une fois exposee, sa signature devient visible automatiquement dans le prompt et dans `lire_capacites()`.

## Intelligence comportementale

### Suggestions contextuelles

Le module `core/contextual_suggestions.py` genere des suggestions intelligentes basees sur plusieurs sources :

- **Patterns comportementaux** : Analyse des horaires d'utilisation, actions repetitives et sequences courantes via `core/pattern_analyzer.py`
- **Etat systeme** : Surveillance du stockage et alertes when seuils critiques sont atteints
- **Contexte temporel** : Suggestions adaptees a l'heure (routine matinale, bilan fin de journee, mode nuit)
- **Contexte utilisateur** : Rappels en attente, automatisations dues, etat de la memoire personnelle
- **Automatisations potentielles** : Detection d'actions repetitives suggerees pour automatisation

### Analyse de performance

Le module `core/decision_analyzer.py` permet a Jarvis de s'auto-analyser :

- **Analyse des decisions recentes** : Taux de succes, outils les plus utilises, erreurs par outil
- **Detection de patterns d'erreur** : Identification des erreurs recurrentes avec suggestions de correction
- **Apprentissage des solutions** : Memorisation des solutions reussies pour reutilisation future
- **Ajustements de strategie** : Recommandations d'amelioration basees sur l'analyse

### Recherche semantique

Le module `core/semantic_search.py` offre des capacites de recherche avancee :

- **Indexation des interactions** : Index automatique des conversations et actions avec mots-cles et thematiques
- **Recherche semantique** : Recherche par pertinence avec scoring base sur mots-cles et themes
- **Analyse de connexions** : Detection des connexions entre differentes thematiques
- **Insights profonds** : Generation d'insights bases sur l'analyse contextuelle

### Surveillance systeme

Le module `core/system_monitor.py` assure une surveillance continue :

- **Monitoring temps reel** : CPU, memoire, disque, reseau, processus
- **Detection d'anomalies** : Alertes automatiques sur les seuils critiques
- **Historique systeme** : Enregistrement des metriques pour analyse des tendances
- **Rapports systeme** : Generation de rapports detailles sur l'etat de la machine

### Personnalite adaptative

Le module `core/personality.py` permet a Jarvis d'adapter son comportement :

- **Traits ajustables** : Sarcasme, formalite, proactivite, humour, empathie, concision, creativite
- **Adaptation contextuelle** : Ajustement du ton en fonction de l'humeur detectee dans le message
- **Evolution automatique** : La personnalite evolue progressivement basee sur les interactions
- **Rapports de personnalite** : Visualisation des traits actuels et de leur evolution

## Interfaces temps reel

L'API FastAPI expose deux flux conversationnels :

- `POST /jarvis/ask` : endpoint compatible, retourne seulement la reponse finale.
- `GET /jarvis/stream?message=...` : endpoint SSE qui transmet les evenements intermediaires (`thinking`, `provider`, `tool_started`, `tool_completed`, `tool_failed`, `confirmation_required`, `stark_activated`, `stark_action`, `stark_terminated`, `response`, `error`, `done`).

Les interfaces `gui/app.py` et `gui/web/index.html` consomment ce flux pour afficher les etapes que le terminal Rich montre deja. Elles ne disposent d'aucun chemin de décision ou d'exécution distinct : API et console passent par `executer_interaction_utilisateur()`.

## Interface vocale et overlay

### Architecture vocale

L'interface vocale de Jarvis est composee de plusieurs modules coordonnes :

- `capabilities/voice_input.py` : Reconnaissance vocale via Vosk avec wake word "Hey Jarvis" et gestion des modes
- `capabilities/voice_output.py` : Synthese vocale (TTS) via Piper avec modeles francais et anglais
- `capabilities/clap_input.py` : Detection de double-clap pour activation vocale alternative
- `core/voice_state.py` : Gestion de l'etat vocal global avec etats : IDLE, LISTENING, THINKING, SPEAKING, ERROR
- `core/voice_overlay.py` : Overlay visuel flottant Tkinter affichant l'etat vocal en temps reel

### Communication etat vocal

L'etat vocal est communique via :

- **Echange memoire** : `core/voice_state.py` utilise un verrou (`threading.Lock`) pour un acces thread-safe
- **Fichier partage** : `voice_state.json` est ecrit par `_write_state_to_file()` pour communication avec l'overlay
- **Polling overlay** : L'overlay lit le fichier JSON toutes les 100ms pour mettre a jour son affichage

### Overlay visuel

L'overlay visuel (`core/voice_overlay.py`) presente les caracteristiques suivantes :

- **Thread Tkinter dedie** : Fonctionne dans un thread separe, compatible avec asyncio/uvicorn
- **Style HUD** : Fond sombre avec lueur cyan, police Segoe UI, titre "JARVIS"
- **Etats visuels distincts** :
  - LISTENING : Cyan + icone ◉ + libellé "ÉCOUTE"
  - THINKING : Orange + icone ◌ + libellé "RÉFLEXION"
  - SPEAKING : Cyan + icone ◈ + libellé "PAROLE"
  - ERROR : Rouge + icône ⚠ + libellé "ERREUR"
  - IDLE : Masque (pas de rendu)
- **Non-intrusif** : Bloque les clics et entrees clavier (pass-through), ne vole pas le focus, pas d'entree dans la barre des taches
- **Positionnement** : Bas-droite de l'ecran par defaut, configurable
- **Integration API** : Demarre automatiquement dans `api/server.py` via `startup_event()`, arrete proprement via `shutdown_event()`

### Serveur FastAPI

`api/server.py` expose `app = FastAPI(title="Jarvis API", version="1.0.0")`.

Routes principales :

- `POST /jarvis/ask` : traitement simple, reponse finale uniquement.
- `GET /jarvis/stream?message=...` : streaming SSE via `StreamingResponse`.
- `GET /jarvis/status` : CPU, RAM et activite detectee.
- `POST /jarvis/signal` : reception de signaux externes.
- `GET /jarvis/alerts` : lecture/vidage des alertes en memoire.
- `POST /jarvis/confirm` : endpoint de confirmation reserve aux extensions.
- `GET /jarvis/discover` : decouverte des appareils Tailscale sur le tailnet pour la gestion multi-instance.
- `POST /jarvis/kill` : endpoint debug garde; l'auto-destruction normale passe par la commande interne `Jarvis, auto-destruction`.
- `/web` : fichiers statiques de `gui/web`.

Au demarrage, le serveur :

1. appelle `initialiser()` pour charger/normaliser `memory.json`;
2. démarre `AutonomousAgent.run()` dans un thread daemon, comme la console;
3. construit l'historique systeme avec `construire_prompt_action(memoire)`;
4. garde `memoire` et `historique` comme etat global du processus API.

Le SSE utilise une `queue.Queue` par connexion. Le thread de travail lie cette queue a `event_bus`, appelle `executer_interaction_utilisateur()`, puis pousse `{"type": "done"}` a la fin. Une action qui requiert une confirmation emet `confirmation_required`; l'interface repond via `POST /jarvis/confirm` avec son `session_id` et l'identifiant de l'action.

### Interfaces

`gui/app.py` :

- client Tkinter local;
- consomme `/jarvis/stream` avec `requests.get(..., stream=True)`;
- met a jour l'UI via `root.after()`;
- desactive le champ de saisie pendant le stream;
- gestion multi-instance avec sélecteur dans le header;
- découverte réseau Tailscale intégrée via `/jarvis/discover`.

`gui/web/index.html` :

- fichier HTML/CSS/JS unique;
- consomme `/jarvis/stream` avec `EventSource`;
- surveille `/jarvis/status`;
- fonctionne depuis un autre appareil du reseau si le port `8000` est accessible;
- gestion multi-instance avec localStorage et sélecteur dans le header;
- découverte réseau Tailscale intégrée via `/jarvis/discover`.

### Démarrage Windows

La tâche planifiée `JarvisAgent` est le mécanisme de démarrage de référence.

Il lance :

```text
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Elle s'exécute sous le compte Windows connecté : CLI, web et Tkinter disposent donc du même profil et des mêmes permissions. `bootstrap/install.ps1` crée ou met à jour cette tâche et désactive le service historique `JarvisService` lorsqu'il existe.

## Securite et permissions

La politique actuelle est une confirmation ciblee, pas un blocage global.

- Les lectures sont libres.
- Les ecritures dans l'espace utilisateur sont libres.
- Les ecritures vers `JARVIS_DIR` ou des zones systeme Windows demandent confirmation.
- `action_bloquee()` est conservee pour compatibilite et retourne toujours `False`.
- En mode Stark, les confirmations sont desactivees pour eviter un blocage interactif pendant une boucle autonome.
- Les automatisations refusent les outils explicitement non automatisables afin d'eviter les actions sensibles ou bloquantes planifiees.

## Gestion des dependances et securite

Jarvis n'effectue **aucune installation de dependance au runtime**.

- **Absence d'auto-installation** : La fonction `_bootstrap_import()` dans `core/safety.py` ne tente jamais d'installer un package via pip. En cas d'import echoue, elle active le mode fallback et retourne None, sans effet de bord reseau ni modification de l'environnement Python.
- **Installation des dependances** : Les dependances doivent etre installees explicitement via `pip install -r requirements.txt` lors de l'installation ou de la mise a jour. Le script `bootstrap/install.ps1` gere cette operation automatiquement.
- **Stabilite des versions** : `requirements.txt` contient des versions strictement bornees pour garantir la reproductibilite. Pour un verrouillage complet avec hashes, la commande suivante peut etre executee : `python -m pip install -r requirements.txt --require-hashes -c constraints.txt` (ou `constraints.txt` est genere par `python -m pip freeze > constraints.txt`).
- **Dependances optionnelles** : Les modules comme `psutil`, `win32api` et `win32security` sont importes via `_bootstrap_import()`. Si absents, Jarvis fonctionne en mode degrade (fallback) sans ces capacites specifiques.

## Securite du PAT GitHub

Le PAT GitHub est manipule de maniere a minimiser son exposition :

- **Jamais dans l'URL Git** : Le PAT n'est jamais inclus dans l'URL du depot ou dans `.git/config`.
- **Mecanisme GIT_ASKPASS** : Les scripts `bootstrap/install.ps1` et `bootstrap/update.ps1` utilisent un script GIT_ASKPASS temporaire qui transmet le PAT uniquement a Git pour l'authentification.
- **Nettoyage automatique** : Le script temporaire et les variables d'environnement sont nettoyes immediatement apres utilisation, meme en cas d'erreur.
- **Jamais dans les logs** : Le PAT n'est jamais journalise ni affiche dans les arguments de processus.
- **Stockage env variable** : Le PAT est stocke uniquement dans la variable d'environnement Machine `GIT_PAT_JARVIS`, accessible uniquement par les scripts d'installation et de mise a jour.

## Memoire et proactivite

- `memory.json` stocke notes, preferences, contexte, automatisations, surveillances, journal d'actions et journal conversationnel.
- `core.memory.normaliser_memoire()` maintient le schema attendu.
- L'agent autonome dans `jarvis.py` observe periodiquement stockage, rappels, automatisations et surveillances, puis affiche uniquement les signaux utiles.
- La proactivite reste discrete : elle suggere ou notifie, mais les actions de rangement/suppression passent par les outils et leurs garde-fous.

## Modules futurs

Le dossier `modules/` contient des modules planifies mais pas encore implementes :

- `modules/context_engine` : Perception du contexte permanent pour une comprehension plus profonde de l'utilisateur
- `modules/datashield` : Protection des donnees sensibles et gestion de la confidentialite
- `modules/progress_tracker` : Suivi des progres sur les taches et projets a long terme
- `modules/syncsphere` : Synchronisation entre differents appareils et services
- `modules/taskflow` : Gestion des flux de taches complexes multi-etapes

Ces modules sont actuellement des squelettes (fichiers `__init__.py` avec documentation) en attente d'implementation.

## Regles de conception

- Core Intellect est le seul composant qui pense.
- `tools.OUTILS` est la surface d'execution publique.
- Les capabilities restent deterministes et petites.
- Les chemins passent par `chemin_autorise()`.
- Les confirmations passent par `demander_confirmation()` ou `confirmer_ecriture_si_requise()`.
- Le contexte durable vient de `memory.json`, pas de l'historique brut envoye au modele.
- Le mode Stark doit rester autonome, structure et economique en tokens.
- Les modules futurs doivent respecter l'architecture existante et ne pas briser les principes de separation des responsabilites.
