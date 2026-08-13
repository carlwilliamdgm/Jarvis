# Jarvis - Assistant IA local

Jarvis est un assistant IA local-first en Python, développé par Carl-William DJEGUEMA pour agir comme compagnon cognitif personnel et agent d'exécution local. Il peut discuter, mémoriser du contexte, exécuter des actions concrètes sur la machine, lancer des boucles agentiques structurées avec le Mode Stark, exposer une API FastAPI et servir des interfaces Tkinter ou web.

Le projet est pensé autour d'un principe simple : le raisonnement est centralisé, les actions sont déterministes, et les interfaces ne font qu'envoyer des messages puis afficher les événements produits par Jarvis.

> **État vérifié le 13 août 2026.** L'API et l'interface web répondent correctement sur le port `8000`, et la suite de tests compte 48 tests passants. Avant de développer de nouvelles fonctionnalités, vérifier la disponibilité du provider LLM choisi, la mémoire disponible et l'espace disque.

## Vue d'ensemble

### Premier lancement ?

Pour une installation et configuration pas à pas, consultez le guide [PREMIER_LANCEMENT.md](PREMIER_LANCEMENT.md).

### Capacités principales

- Assistant conversationnel local avec mémoire persistante.
- Exécution d'outils réels via `tools.OUTILS`.
- Conscience dynamique des capacités grâce à l'inventaire temps réel de `core/tool_signatures.py`.
- Mode Stark pour les objectifs multi-étapes avec grammaire `>>`, `&&`, `||`.
- Mode action one-shot avec `!a`.
- API FastAPI sur le port `8000`.
- Streaming SSE pour afficher les événements intermédiaires en direct.
- Interface Tkinter locale dans `gui/app.py`.
- Interface web multi-device servie par FastAPI dans `gui/web/index.html`.
- Service Windows pywin32 capable de lancer automatiquement `uvicorn api.server:app`.
- Mémoire, rappels, automatisations, surveillance de dossiers, stockage, commandes shell/PowerShell et commandes personnalisées.

### Surfaces utilisateur

| Surface | Fichier | Usage |
| --- | --- | --- |
| Console Rich | `jarvis.py` | Utilisation terminal complète |
| API FastAPI | `api/server.py` | Intégration locale, web, multi-device |
| Interface Tkinter | `gui/app.py` | Client desktop local consommant le SSE |
| Interface web | `gui/web/index.html` | Client navigateur servi sur `/web` |
| Service Windows | `service/windows_service.py` | Démarrage automatique de l'API |

## Prérequis

### Environnement cible

- Windows est la plateforme principale.
- Python recommandé : Python 3.12 (chemin détecté automatiquement par le script d'installation).
- Dossier projet : `%USERPROFILE%\Jarvis` (configurable via paramètre d'installation).
- Packages utilisateur : détecté automatiquement par le script d'installation.

### Dépendances Python

Le fichier `requirements.txt` contient les dépendances historiques du projet. Selon la surface utilisée, ces packages doivent aussi être présents :

- `fastapi`
- `uvicorn`
- `requests`
- `pywin32` pour le service Windows
- `psutil`
- `rich`
- `ollama`
- `groq`
- `plyer`

Installation typique :

```powershell
cd %USERPROFILE%\Jarvis
python -m pip install -r requirements.txt
python -m pip install fastapi uvicorn requests pywin32
```

Avec un chemin Python explicite (si nécessaire) :

```powershell
& "C:\Program Files\Python312\python.exe" -m pip install -r requirements.txt
& "C:\Program Files\Python312\python.exe" -m pip install fastapi uvicorn requests pywin32
```

Pour exécuter la suite de tests, installer également `pytest` dans **le même environnement Python que Jarvis**. Le projet peut être utilisé avec un environnement virtuel `.venv` :

```powershell
cd %USERPROFILE%\Jarvis
.\.venv\Scripts\python.exe -m pip install pytest
```

### Providers LLM

Jarvis peut utiliser :

- Groq via `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, etc.
- OpenRouter via `OPENROUTER_API_KEY`.
- Ollama local avec `qwen2.5:7b` en fallback.

Exemple PowerShell :

```powershell
$env:GROQ_API_KEY="votre_cle"
$env:OPENROUTER_API_KEY="votre_cle"
```

Pour Ollama :

```powershell
ollama serve
ollama pull qwen2.5:7b
```

## Lancer Jarvis

### 1. Console Rich

La console est l'expérience directe historique.

```powershell
cd %USERPROFILE%\Jarvis
python jarvis.py
```

Ou avec le Python explicite :

```powershell
cd %USERPROFILE%\Jarvis
& "C:\Program Files\Python312\python.exe" jarvis.py
```

Sur Windows, `jarvis.cmd` peut aussi servir de raccourci (il utilise le chemin dynamique du script).

### 2. Serveur FastAPI manuel

Le serveur expose l'API, le streaming SSE et l'interface web.

```powershell
cd %USERPROFILE%\Jarvis
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Avec le Python explicite :

```powershell
cd %USERPROFILE%\Jarvis
& "C:\Program Files\Python312\python.exe" -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

URLs principales :

- API locale : `http://localhost:8000`
- Interface web locale : `http://localhost:8000/web`
- Documentation OpenAPI FastAPI : `http://localhost:8000/docs`
- Depuis un autre appareil du réseau : `http://ADRESSE_IP_DE_LA_MACHINE:8000/web`

Le serveur initialise la mémoire avec `initialiser()`, construit un historique système avec `construire_prompt_action()`, puis attend les requêtes.

### 3. Interface Tkinter

L'interface Tkinter est un client local. Elle ne lance pas l'API elle-même : le serveur FastAPI doit déjà tourner.

```powershell
cd %USERPROFILE%\Jarvis
python gui\app.py
```

Elle consomme :

- `GET /jarvis/stream?message=...` pour la conversation en direct.
- Les événements SSE pour afficher réflexion, provider, actions Stark, erreurs et réponse finale.

### 4. Interface web

L'interface web est un fichier unique :

```text
gui/web/index.html
```

Elle est servie par FastAPI grâce au mount :

```python
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")
```

Accès :

```text
http://localhost:8000/web
```

Pour mobile/tablette sur le même réseau, utiliser l'adresse IP locale de la machine qui exécute Jarvis :

```text
http://192.168.x.x:8000/web
```

Le navigateur utilise `EventSource` natif, sans framework ni dépendance externe.

### 5. Service Windows

Le service Windows lance automatiquement :

```text
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Fichier :

```text
service/windows_service.py
```

Caractéristiques :

- Utilise le chemin Python détecté lors de l'installation (variable d'environnement `JARVIS_PYTHON_EXE`).
- Ajoute les packages utilisateur détectés au path (variable d'environnement `JARVIS_USER_SITE_PACKAGES`).
- Lance uniquement `uvicorn api.server:app`.
- Ne charge pas `jarvis.py` comme agent console.
- Écrit les logs dans :
  - `service/jarvis_service.log`
  - `service/uvicorn.log`

Installation :

```powershell
cd %USERPROFILE%\Jarvis
python service\windows_service.py install
```

Démarrage :

```powershell
net start JarvisService
```

Arrêt :

```powershell
net stop JarvisService
```

Suppression :

```powershell
cd %USERPROFILE%\Jarvis
python service\windows_service.py remove
```

### Configuration du démarrage automatique

Par défaut, le service est configuré en démarrage manuel. Pour le démarrer automatiquement au démarrage de Windows :

```powershell
sc config JarvisService start= auto
```

Options de démarrage disponibles :
- `auto` : Démarrage automatique au démarrage de Windows
- `demand` : Démarrage manuel (par défaut)
- `delayed-auto` : Démarrage automatique différé (recommandé pour éviter de surcharger le démarrage)

### Vérification de l'état du service

Vérifier si le service est en cours d'exécution :

```powershell
sc query JarvisService
```

Attendu :
```
STATE              : 4 RUNNING
```

Vérifier les logs du service :

```powershell
type service\jarvis_service.log
```

Vérifier les logs uvicorn :

```powershell
type service\uvicorn.log
```

Tester l'API :

```powershell
curl.exe "http://localhost:8000/jarvis/status"
```

Attendu : JSON avec CPU, RAM et active status.

Redémarrage :

```powershell
net stop JarvisService
net start JarvisService
```

Ces commandes nécessitent généralement un PowerShell administrateur.

## API FastAPI

Point d'entrée :

```text
api/server.py
```

Application :

```python
app = FastAPI(title="Jarvis API", version="1.0.0")
```

### `POST /jarvis/ask`

Endpoint de compatibilité. Il retourne uniquement la réponse finale.

Requête :

```json
{
  "message": "bonjour"
}
```

Réponse :

```json
{
  "response": "Bonjour, Sir.",
  "is_action": false,
  "actions_executed": []
}
```

Usage curl :

```powershell
curl.exe -X POST "http://localhost:8000/jarvis/ask" `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"bonjour\"}"
```

### `GET /jarvis/stream?message=...`

Endpoint recommandé pour les interfaces. Il retourne un flux SSE `text/event-stream`.

Usage curl :

```powershell
curl.exe -N "http://localhost:8000/jarvis/stream?message=bonjour"
```

Format SSE :

```text
data: {"type":"thinking","data":{"message":"Jarvis réfléchit..."}}

data: {"type":"response","data":{"text":"Bonjour, Sir.","is_action":false,"timestamp":"08:14:40"}}

data: {"type":"done"}
```

Événements possibles :

| Type | Données | Usage |
| --- | --- | --- |
| `thinking` | `{"message": "Jarvis réfléchit..."}` | Statut de réflexion |
| `provider` | `{"provider": "Groq", "model": "llama-3.3-70b-versatile"}` | Provider LLM utilisé |
| `tool_started` | `{"outil": "...", "args": {}, "mode": "normal|stark"}` | Début d'une action réelle |
| `tool_completed` | `{"outil": "...", "resultat": "...", "mode": "normal|stark"}` | Action terminée |
| `tool_failed` | `{"outil": "...", "resultat": "...", "mode": "normal|stark"}` | Action en erreur ou refusée |
| `confirmation_required` | `{"action_id": "...", "description": "...", "expires_at": "..."}` | Décision utilisateur attendue |
| `stark_activated` | `{"objectif": "..."}` | Début du Mode Stark |
| `stark_action` | `{"outil": "...", "args": {}, "resultat": "...", "erreur": false}` | Action Stark exécutée |
| `stark_terminated` | `{"statut": "terminé|interrompu", "rapport": "..."}` | Rapport Stark final |
| `response` | `{"text": "...", "is_action": false, "timestamp": "HH:MM:SS"}` | Réponse finale |
| `error` | `{"message": "..."}` | Erreur |
| `done` | aucun champ `data` obligatoire | Fin du flux |

Implémentation technique :

- `api/server.py` crée une queue SSE par connexion.
- `jarvis.event_bus` lie la queue au thread de travail.
- `executer_interaction_utilisateur()` est le pipeline commun console/API : préparation, exécution et journalisation; `executer_agent()` émet les événements.
- Le générateur SSE sérialise chaque événement avec `json.dumps(..., ensure_ascii=False)`.

### `GET /jarvis/status`

Retourne un état léger de la machine.

Réponse :

```json
{
  "cpu": 12.5,
  "ram": 48.2,
  "active": true
}
```

### `POST /jarvis/signal`

Reçoit un signal externe.

Requête :

```json
{
  "device": "telephone",
  "event_type": "battery",
  "payload": {
    "level": 42
  }
}
```

Réponse :

```json
{
  "received": true
}
```

### `GET /jarvis/alerts`

Retourne puis vide la queue d'alertes en mémoire.

```json
{
  "alerts": []
}
```

### `GET /jarvis/discover`

Découvre les appareils Tailscale sur le tailnet pour faciliter l'ajout d'instances distantes.

Réponse :

```json
{
  "devices": [
    {
      "nom": "PC2",
      "ip": "100.x.x.x"
    }
  ]
}
```

Retourne une erreur 503 si Tailscale n'est pas disponible sur l'instance.

### `POST /jarvis/confirm`

Résout une confirmation demandée pendant un flux SSE. L'interface conserve son
`session_id`, reçu/choisi lors de l'ouverture du flux, puis répond avec l'identifiant
de l'action fournie par l'événement `confirmation_required`.

```json
{
  "session_id": "session-interface",
  "action_id": "abc",
  "confirmed": true
}
```

### `POST /jarvis/kill`

Endpoint debug gardé explicitement. L'auto-destruction normale se déclenche par la commande interne en deux temps :

1. `Jarvis, auto-destruction`
2. `Jarvis, confirme auto-destruction` dans les 30 secondes

L'appel HTTP direct est refusé sauf si `JARVIS_ALLOW_HTTP_KILL=1` et le header `X-Jarvis-Internal-Kill: true` sont présents.

Réponse immédiate :

```json
{
  "status": "kill_initiated"
}
```

La destruction s'effectue en arrière-plan avec un délai de 2 secondes après la réponse HTTP. La séquence d'effacement est :

1. Arrêt et suppression du service Windows JarvisService (sc.exe)
2. Suppression de la tâche planifiée JarvisAutoUpdate (PowerShell)
3. Suppression des variables d'environnement Machine-level :
   - GIT_PAT_JARVIS
   - JARVIS_INSTALL_DIR
   - JARVIS_PYTHON_EXE
   - JARVIS_PYTHON_ARGS
   - JARVIS_USER_SITE_PACKAGES
   - GROQ_API_KEY_1 à GROQ_API_KEY_5
   - OPENROUTER_API_KEY
4. Suppression du modèle Ollama `qwen2.5:7b` si aucune autre installation Jarvis locale active n'est détectée
5. Suppression complète du dossier Jarvis (C:\Users\<USERPROFILE>\Jarvis)

Chaque étape continue même si la précédente échoue. Aucune erreur n'est retournée après le 200 initial (connexion déjà fermée).

## Interfaces

### Tkinter

Fichier :

```text
gui/app.py
```

Comportement :

- Envoie les messages à `/jarvis/stream`.
- Lit le SSE avec `requests.get(..., stream=True)`.
- Utilise un thread réseau séparé.
- Met à jour l'UI uniquement avec `root.after(0, callback)`.
- Désactive l'input pendant la réponse.
- Réactive l'input à `done`.
- Affiche tous les événements intermédiaires, pas seulement la réponse finale.
- Gestion multi-instance : sélecteur d'instance dans le header, ajout/modification/suppression d'instances distantes.
- Découverte réseau Tailscale intégrée pour détecter automatiquement les appareils Jarvis sur le tailnet.

### Web

Fichier :

```text
gui/web/index.html
```

Contraintes :

- HTML, CSS et JS inline.
- Aucune dépendance externe.
- Aucun framework.
- Responsive mobile/tablette/desktop.

Comportement :

- Utilise `EventSource`.
- Ferme proprement le stream à `done`.
- Désactive l'input pendant le stream.
- Affiche le statut du service via `/jarvis/status`.
- Peut être utilisé depuis un autre appareil du réseau si le port `8000` est accessible.
- Gestion multi-instance : sélecteur d'instance dans le header, ajout/modification/suppression d'instances distantes via localStorage.
- Découverte réseau Tailscale intégrée pour détecter automatiquement les appareils Jarvis sur le tailnet.

## Modes de conversation

### Mode normal

Le message est transmis à `core.intellect.interpreter_objectif()`. Core Intellect renvoie :

```json
{
  "objectif": "description",
  "type": "action|conversation|diagnostic|planification|mixte",
  "actions": [],
  "reponse": "réponse naturelle"
}
```

Jarvis exécute ensuite les actions listées via `tools.OUTILS`.

### Mode action one-shot

Activation :

```text
!a
```

Ou :

```text
Jarvis, passe en mode action
```

Le prochain message est traité comme une commande directe, puis le mode est remis à zéro.

### Mode Stark

Activation :

```text
!S <objectif>
```

Exemple :

```text
!S audite le stockage >> liste les gros fichiers && (notifie le résultat || note le résultat)
```

Grammaire :

- `>>` : macro-étapes séquentielles.
- `&&` : dépendance gauche-droite.
- `||` : alternatives/replis.

Le Mode Stark :

- active `core.safety.activer_mode_stark()`;
- court-circuite les confirmations interactives;
- exécute des micro-objectifs avec budget limité;
- produit un rapport final;
- émet les événements SSE `stark_activated`, `stark_action` et `stark_terminated`.

## Conscience des capacités

Jarvis sait ce qu'il peut faire grâce à l'inventaire dynamique des outils.

Fichier :

```text
core/tool_signatures.py
```

Principe :

- `tools.OUTILS` est le registre public réel.
- `core/tool_signatures.py` introspecte ce registre avec `inspect.signature`.
- `documenter_signatures_outils()` injecte les signatures actuelles dans les prompts.
- `lire_capacites()` expose le même inventaire comme outil Jarvis.

Conséquence :

- Si un outil est ajouté dans `tools.OUTILS`, Jarvis le voit dans son prompt.
- Si un outil est retiré de `tools.OUTILS`, Jarvis ne doit plus le proposer.
- La documentation ne doit pas être la source de vérité des capacités. Elle explique le mécanisme ; le registre actif reste `tools.OUTILS`.

Demande utilisateur typique :

```text
Jarvis, qu'est-ce que tu peux faire maintenant ?
```

Réponse attendue côté modèle :

1. Appeler `lire_capacites()`.
2. Résumer les capacités disponibles en langage naturel.
3. Être honnête sur les limites.

## Architecture technique

```text
jarvis.py
├── EventBus
├── detecter_commande_mode()
├── parler()
├── executer_agent()
├── executer_mode_stark()
└── AutonomousAgent

api/server.py
├── FastAPI app
├── /jarvis/ask
├── /jarvis/stream
├── /jarvis/status
└── /web

core/
├── intellect.py
├── prompt.py
├── tool_signatures.py
├── memory.py
├── safety.py
├── stark_parser.py
└── stark_session.py

tools.py
└── OUTILS

capabilities/
├── files.py
├── storage.py
├── commands.py
├── organization.py
├── memory_tools.py
├── scheduler.py
├── custom_commands.py
└── watchers.py
```

### Responsabilités

- `core/intellect.py` : seul composant qui raisonne.
- `jarvis.py` : orchestration, modes, exécution, EventBus, agent autonome.
- `tools.py` : façade publique des outils.
- `capabilities/` : exécution déterministe.
- `api/server.py` : transport HTTP/SSE et fichiers statiques.
- `gui/app.py` et `gui/web/index.html` : présentation.
- `service/windows_service.py` : intégration Windows.

## Outils principaux

Les outils sont exposés via `tools.OUTILS`. La liste réelle est consultable à tout moment avec :

```text
lire_capacites()
```

Familles principales :

- Fichiers : créer, lire, lister, supprimer.
- Stockage : audit, fichiers lourds, temp, corbeille.
- Mémoire : notes, préférences, contexte durable.
- Organisation : analyse et rangement de dossiers.
- Rappels : ajout, lecture, suppression, vérification.
- Automatisations : création, liste, exécution manuelle ou due.
- Surveillance : dossiers surveillés et exécution des surveillances.
- Commandes : shell, PowerShell, commandes personnalisées.
- Traducteur : consultation et demande de modification.
- Agentique : `terminer_tache()`, `bilan_proactif()`.
- Introspection : `lire_capacites()`.

## Mémoire et fichiers d'état

### `memory.json`

Stocke :

- notes;
- préférences;
- contexte personnel structuré;
- journal conversationnel;
- historique d'actions;
- automatisations;
- surveillances de dossiers;
- signaux proactifs.

### `stark_actif.json`

Stocke les instances Stark actives pour éviter les collisions et détecter les sessions mortes.

### Logs

Service Windows :

```text
service/jarvis_service.log
service/uvicorn.log
```

## Sécurité

La politique actuelle est une confirmation ciblée :

- Les lectures sont libres.
- Les écritures dans l'espace utilisateur sont libres.
- Les écritures vers `JARVIS_DIR` ou zones système Windows demandent confirmation.
- En Mode Stark, les confirmations sont désactivées pour éviter un blocage interactif.
- Les automatisations refusent certains outils sensibles ou bloquants.

Les chemins passent par `core.safety.chemin_autorise()` lorsque l'outil manipule le système de fichiers.

## Tests et validation

La commande de référence utilise l'environnement virtuel du projet lorsqu'il existe :

```powershell
cd %USERPROFILE%\Jarvis
.\.venv\Scripts\python.exe -m pytest -q
```

Résultat de la dernière vérification : `48 passed`.

Compilation rapide :

```powershell
cd %USERPROFILE%\Jarvis
python -m py_compile jarvis.py api\server.py gui\app.py tools.py core\tool_signatures.py
```

Tester l'API :

```powershell
curl.exe "http://localhost:8000/jarvis/status"
```

Tester le SSE :

```powershell
curl.exe -N "http://localhost:8000/jarvis/stream?message=bonjour"
```

Tester le web sans navigateur via FastAPI TestClient :

```powershell
python -c "from fastapi.testclient import TestClient; from api.server import app; r=TestClient(app).get('/web/'); print(r.status_code)"
```

Tester les signatures dynamiques :

```powershell
python -c "import tools; print(tools.OUTILS['lire_capacites']())"
```

## Dépannage

### `/jarvis/stream` retourne `404 Not Found`

Cause probable : le service Windows ou le serveur manuel tourne encore avec une ancienne version du code.

Solution :

```powershell
net stop JarvisService
net start JarvisService
```

Ou arrêter puis relancer le serveur manuel `uvicorn`.

### `http://localhost:8000/web` ne charge pas

Vérifier :

- le serveur FastAPI est lancé;
- `api/server.py` contient bien le mount `/web`;
- le fichier `gui/web/index.html` existe;
- l'URL utilisée est `/web` ou `/web/`.

### L'interface Tkinter affiche Jarvis hors ligne

Vérifier :

- le serveur FastAPI tourne sur `localhost:8000`;
- `/jarvis/stream?message=bonjour` répond avec `curl.exe -N`;
- aucun firewall local ne bloque la connexion.

### Ollama est indisponible

Les fonctions qui utilisent le fallback local ne peuvent pas générer de réponse tant qu'Ollama n'est pas démarré. L'API et l'interface web peuvent néanmoins rester accessibles.

```powershell
ollama serve
ollama pull qwen2.5:7b
```

Si un provider distant est configuré, vérifier la présence de la variable correspondante (`GROQ_API_KEY` ou `OPENROUTER_API_KEY`) dans l'environnement du processus qui lance Jarvis.

### La machine manque de ressources

Consulter `GET /jarvis/status` pour la charge CPU, l'usage mémoire et l'état de l'API. Maintenir une marge d'espace disque et de mémoire avant d'exécuter des tâches autonomes ou intensives.

### Le service Windows refuse de démarrer

Consulter :

```text
service/jarvis_service.log
service/uvicorn.log
```

Vérifier :

- Python est installé et détecté par le script d'installation;
- `pywin32`, `fastapi`, `uvicorn` sont installés pour ce Python;
- le port `8000` n'est pas déjà occupé;
- les commandes sont lancées en administrateur.

### Jarvis ne sait pas faire une action

Vérifier :

- l'outil existe dans `tools.OUTILS`;
- sa signature apparaît dans `lire_capacites()`;
- Core Intellect n'a pas filtré l'action comme outil inconnu;
- les paramètres demandés correspondent à la signature réelle.

## Règles pour ajouter une capacité

1. Créer ou modifier une fonction déterministe dans `capabilities/`.
2. Ajouter un wrapper dans `tools.py` si une confirmation, normalisation ou journalisation est nécessaire.
3. Exposer l'outil dans `tools.OUTILS`.
4. Vérifier que `lire_capacites()` affiche la nouvelle signature.
5. Ajouter ou adapter les tests.
6. Mettre à jour la documentation métier si l'outil ajoute un nouveau domaine fonctionnel.

Ne pas appeler directement un LLM depuis `capabilities/`.

## Modules futurs

Le dossier `modules/` contient des modules planifiés :

- `context_engine` : perception du contexte permanent.
- `datashield` : protection des données sensibles.
- `progress_tracker` : suivi long terme.
- `syncsphere` : synchronisation multi-appareils.
- `taskflow` : workflows complexes.

Ils doivent respecter les principes existants : Core Intellect pense, les capabilities exécutent, `tools.OUTILS` expose.

## Licence

À définir.

## Crédit

Développé par Carl-William DJEGUEMA - The Great Corporation.
