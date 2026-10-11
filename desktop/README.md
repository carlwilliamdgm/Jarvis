# Client desktop GreatOS (Windows)

Le client Electron/React s'appuie sur le serveur FastAPI existant. Les contrats
restent ceux de `interface_morphique/server.py`; le HUD Windows natif est
conservé pendant la migration.

## Développement

Depuis ce répertoire, lancer `npm install`, puis `npm run desktop:dev`. Cette
commande démarre l'API locale, Vite et Electron. Le renderer de développement
écoute sur `127.0.0.1:5173`; l'API autorise explicitement cette origine.

## Build Windows

`npm run desktop:build` génère les assets React et l'installeur Electron NSIS.
Le serveur GreatOS doit être démarré sur `127.0.0.1:8000` avant d'ouvrir le
client distribué; `GREATOS_DESKTOP_URL` permet de sélectionner une autre URL
pour le client desktop.

## Capacités portées

- conversation SSE, statut du provider et commandes d'arrêt;
- dialogue de confirmation par `/jarvis/confirm`;
- statut système, micro, vision, chiffrement et sessions navigateur;
- layout contextuel provenant de `/jarvis/layout` et des événements SSE;
- thèmes et sélection/ajout d'instances locales ou distantes.

Le moteur de layout décide du contexte. Le client l'affiche et adapte sa surface;
il ne force pas un layout concurrent au serveur.
