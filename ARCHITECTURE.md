# Architecture Jarvis

Jarvis est un agent IA local-first. Le modele raisonne, `memory.json` porte le contexte profond, et les outils executent les actions locales avec garde-fous.

## Points d'entree

- `jarvis.py` : interface console, routage modele, parsing JSON, veille proactive.
- `jarvis.cmd` : lancement Windows.
- `monitor.py` : compatibilite pour lancer uniquement la surveillance stockage.

## Core

- `core/paths.py` : chemins, OS, racines autorisees.
- `core/memory.py` : lecture/ecriture de `memory.json`, normalisation, journal local.
- `core/safety.py` : validation des chemins, actions sensibles, commandes autorisees.
- `core/prompt.py` : construction du prompt systeme depuis `memory.json`.

## Capabilities

- `capabilities/files.py` : fichiers et dossiers.
- `capabilities/storage.py` : stockage, temp, corbeille, fichiers lourds.
- `capabilities/commands.py` : execution de commandes autorisees.
- `capabilities/organization.py` : analyse et rangement de dossiers.
- `capabilities/memory_tools.py` : notes, preferences, contexte personnel.
- `capabilities/scheduler.py` : rappels et automatisations.
- `capabilities/custom_commands.py` : raccourcis utilisateur.
- `capabilities/watchers.py` : surveillance proactive de dossiers.

## Facade outils

`tools.py` expose `OUTILS`, gere les confirmations, le bilan proactif, et conserve la compatibilite avec les imports existants.

## Regles de conception

- Les actions sensibles passent par `demander_confirmation`.
- Les chemins sont controles par `chemin_autorise`.
- Le dossier home complet ne doit pas etre organise directement.
- La proactivite reste discrete par defaut.
- L'organisation proactive surveille et signale ; elle ne range pas automatiquement sans confirmation.
- Le contexte long terme vient de `memory.json`, pas de l'historique brut du modele.
