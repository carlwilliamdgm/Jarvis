# Client desktop GreatOS (Windows)

Le client Electron/React appartient au module Interface Morphique et s'appuie
sur le serveur FastAPI existant. Les contrats restent ceux de
`interface_morphique/server.py`; le HUD Windows natif est conservé pendant la
migration.

## Développement

Depuis `interface_morphique/desktop`, lancer `npm install`, puis
`npm run desktop:dev`. Cette
commande démarre l'API locale, Vite et Electron. Le renderer de développement
écoute sur `127.0.0.1:5173`; l'API autorise explicitement cette origine.

## Build Windows

`npm run desktop:build` génère les assets React et l'installeur Electron NSIS.
Le service GreatOS doit être installé sur la machine Windows (script
`install.ps1`, qui enregistre la tâche planifiée `JarvisAgent`). Le client
vérifie l'API locale et démarre cette tâche si nécessaire; il attend au plus
90 secondes. En cas d'échec, il propose de réessayer et indique le service à
vérifier. Aucun deuxième serveur n'est lancé par Electron.

`GREATOS_DESKTOP_URL` permet de sélectionner une autre URL pour le client
desktop; le démarrage automatique du service local s'applique uniquement à
l'URL locale par défaut.

## Capacités portées

- conversation SSE, statut du provider et commandes d'arrêt;
- dialogue de confirmation par `/jarvis/confirm`;
- statut système, micro, vision, chiffrement et sessions navigateur;
- layout contextuel provenant de `/jarvis/layout` et des événements SSE;
- thèmes et sélection/ajout d'instances locales ou distantes.

Le moteur de layout décide du contexte. Le client l'affiche et adapte sa surface;
il ne force pas un layout concurrent au serveur.
