# Architecture Jarvis

Jarvis est un agent IA local-first en Python. Le composant qui raisonne est `core/intellect.py`; le reste du système orchestre, sécurise, persiste ou exécute. `memory.json` porte le contexte long terme, tandis que l'historique de conversation reste volontairement limité.

## Points d'entree

- `jarvis.py` : interface console, boucle principale, commandes de mode, orchestration des actions, mode Stark et agent autonome de veille.
- `jarvis.cmd` : lancement Windows.
- `monitor.py` : compatibilite pour lancer uniquement la surveillance stockage.
- `api/server.py` : point d'entree serveur API local.
- `gui/app.py` : interface graphique.
- `service/windows_service.py` : integration service Windows.

## Flux principal

1. La boucle console reçoit le message utilisateur dans `jarvis.py`.
2. `detecter_commande_mode()` intercepte les commandes locales (`!a`, `!S <objectif>`, activation/desactivation du mode action).
3. Hors commande spéciale, `parler()` appelle `core.intellect.interpreter_objectif()`.
4. Core Intellect renvoie une structure normalisee : objectif, type, actions et reponse naturelle.
5. `jarvis.py` execute les actions listées via `tools.OUTILS`, puis assemble la reponse finale.
6. L'echange est journalisé dans la memoire persistante.

Le modèle ne doit pas être appelé directement depuis les capabilities. Si une fonctionnalité doit "penser", elle remonte au Core Intellect ou reste une execution deterministe.

## Core

- `core/intellect.py` : cerveau unique de Jarvis. Construit le prompt d'interpretation, appelle les modeles, parse le JSON de decision et filtre les outils inconnus.
- `core/prompt.py` : prompts systeme historiques et prompts d'action/conversation utilises par certaines surfaces.
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
- Chaque micro-objectif a un budget local de `MAX_ETAPES_PAR_MICRO_OBJECTIF = 3`.
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
- fournir `bilan_proactif()`, `terminer_tache()` et les outils de consultation du traducteur.

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

## Regles de conception

- Core Intellect est le seul composant qui pense.
- `tools.OUTILS` est la surface d'execution publique.
- Les capabilities restent deterministes et petites.
- Les chemins passent par `chemin_autorise()`.
- Les confirmations passent par `demander_confirmation()` ou `confirmer_ecriture_si_requise()`.
- Le contexte durable vient de `memory.json`, pas de l'historique brut envoye au modele.
- Le mode Stark doit rester autonome, structure et economique en tokens.
