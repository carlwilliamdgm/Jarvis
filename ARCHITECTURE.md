# Architecture Jarvis

Jarvis est un agent IA local-first en Python. Le composant qui raisonne est `core/intellect.py`; le reste du système orchestre, sécurise, persiste ou exécute. `memory.json` porte le contexte long terme, tandis que l'historique de conversation reste volontairement limité.

## Points d'entree

- `jarvis.py` : interface console, boucle principale, commandes de mode, orchestration des actions, mode Stark et agent autonome de veille.
- `jarvis.cmd` : lancement Windows.
- `monitor.py` : compatibilite pour lancer uniquement la surveillance stockage.
- `api/server.py` : point d'entree serveur FastAPI local, API REST, SSE et fichiers web statiques.
- `gui/app.py` : interface graphique Tkinter, cliente du flux SSE.
- `gui/web/index.html` : interface web autonome servie par `/web`.
- `service/windows_service.py` : integration service Windows qui lance `uvicorn api.server:app`.

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

## Interfaces temps reel

L'API FastAPI expose deux flux conversationnels :

- `POST /jarvis/ask` : endpoint compatible, retourne seulement la reponse finale.
- `GET /jarvis/stream?message=...` : endpoint SSE qui transmet les evenements intermediaires (`thinking`, `provider`, `tool_started`, `tool_completed`, `tool_failed`, `confirmation_required`, `stark_activated`, `stark_action`, `stark_terminated`, `response`, `error`, `done`).

Les interfaces `gui/app.py` et `gui/web/index.html` consomment ce flux pour afficher les etapes que le terminal Rich montre deja. Elles ne disposent d'aucun chemin de décision ou d'exécution distinct : API et console passent par `executer_interaction_utilisateur()`.

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

### Service Windows

`service/windows_service.py` declare `JarvisService`.

Il lance :

```text
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Le service utilise les chemins détectés lors de l'installation :

- Chemin Python : variable d'environnement `JARVIS_PYTHON_EXE`
- Packages utilisateur : variable d'environnement `JARVIS_USER_SITE_PACKAGES`

Ces variables sont définies automatiquement par le script d'installation `bootstrap/install.ps1`.

Logs :

- `service/jarvis_service.log` pour le cycle de vie du service;
- `service/uvicorn.log` pour stdout/stderr du serveur.

## Securite et permissions

La politique actuelle est une confirmation ciblee, pas un blocage global.

- Les lectures sont libres.
- Les ecritures dans l'espace utilisateur sont libres.
- Les ecritures vers `JARVIS_DIR` ou des zones systeme Windows demandent confirmation.
- `action_bloquee()` est conservee pour compatibilite et retourne toujours `False`.
- En mode Stark, les confirmations sont desactivees pour eviter un blocage interactif pendant une boucle autonome.
- Les automatisations refusent les outils explicitement non automatisables afin d'eviter les actions sensibles ou bloquantes planifiees.

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
