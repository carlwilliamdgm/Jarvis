# Jarvis - Assistant IA local

Jarvis est un assistant IA local-first en Python, développé par Carl-William DJEGUEMA pour agir comme compagnon cognitif personnel et agent d'exécution local. Il peut discuter, mémoriser du contexte, exécuter des actions concrètes sur la machine, lancer des boucles agentiques structurées avec le Mode Stark, exposer une API FastAPI et servir des interfaces Tkinter ou web.

Le projet est pensé autour d'un principe simple : le raisonnement est centralisé, les actions sont déterministes, et les interfaces ne font qu'envoyer des messages puis afficher les événements produits par Jarvis.

> **État vérifié le 18 août 2026.** L'API et l'interface web répondent correctement sur le port `8000`, et la suite de tests compte 69 tests passants (57 tests rapides + 12 tests lents). Avant de développer de nouvelles fonctionnalités, vérifier la disponibilité du provider LLM choisi, la mémoire disponible et l'espace disque.

## Vue d'ensemble

### Premier lancement ?

Pour une installation et configuration pas à pas, consultez le guide [PREMIER_LANCEMENT.md](PREMIER_LANCEMENT.md).

### Fonctionnalités avancées

### Interface vocale et overlay visuel

Jarvis dispose d'une interface vocale complète avec un indicateur visuel temps réel :

- **Reconnaissance vocale** : 
  - Wake word "Hey Jarvis" via Vosk
  - Activation par double-clap via clap detection
  - Modèles vocaux locaux (français et anglais)
  
- **Synthèse vocale (TTS)** :
  - Réponses vocales via Piper
  - Modèles voix français et anglais
  - Contrôle de la vitesse et du ton

- **Overlay visuel vocal** :
  - HUD flottant en bas-droite de l'écran
  - États visuels distincts : ÉCOUTE (cyan), RÉFLEXION (orange), PAROLE (cyan), ERREUR (rouge)
  - Communication via fichier `voice_state.json` partagé
  - Non-intrusif : passe les clics à travers, ne vole pas le focus
  - Démarrage automatique avec JarvisAgent

### Modèle souverain Jarvis-GC

Jarvis dispose d'un modèle souverain propriétaire développé par The Great Corporation :

- **Base technique** : Qwen 2.5 (1.5B/3B/7B Instruct) optimisé pour CPU/AVX2
- **Optimisation Windows** : Utilisation de 4 threads physiques pour éviter le freeze système
- **Prompt système gravé** : Instructions gravées dans le Modelfile pour cohérence maximale
- **Timeout stricte** : Délai configurable (45s par défaut) pour garantir réactivité
- **Décodage structuré** : Optimisé pour le tool calling et la prise de décision
- **Gestion éco mémoire** : Déchargement automatique après 5min d'inactivité
- **Fonctionnement hors-ligne** : Premier choix quand les providers cloud sont indisponibles

**Installation du modèle** :
```powershell
ollama serve
ollama create jarvis-gc -f models/jarvis_gc/Modelfile
```

**Configuration avancée** :
```powershell
# Timeout personnalisé (secondes)
$env:JARVIS_GC_TIMEOUT="60"

# Nombre de threads (défaut: 4)
$env:JARVIS_GC_THREADS="8"

# Host Ollama personnalisé
$env:JARVIS_MODEL_HOST="http://127.0.0.1:11434"
```

### Intelligence comportementale

- **Suggestions contextuelles** : Jarvis propose des actions basées sur vos habitudes, l'heure actuelle, l'état système et votre contexte utilisateur
- **Analyse de patterns** : Détection automatique des actions répétitives, séquences courantes et horaires d'utilisation
- **Apprentissage** : Mémorisation des solutions réussies pour réutilisation future, détection de patterns d'erreur récurrents
- **Recherche sémantique** : Indexation de l'historique des interactions avec recherche par mots-clés et thématiques

### Surveillance système

- **Monitoring continu** : CPU, mémoire, disque, réseau, processus
- **Détection d'anomalies** : Alertes automatiques sur les seuils critiques (CPU > 90%, mémoire > 90%, disque > 95%)
- **Historique système** : Enregistrement des métriques pour analyse des tendances
- **Rapports système** : Générations de rapports détaillés sur l'état de la machine

### Personnalité adaptative

- **Traits ajustables** : Sarcasme, formalité, proactivité, humour, empathie, concision, créativité
- **Adaptation contextuelle** : Ajustement du ton en fonction de l'humeur détectée dans le message
- **Évolution automatique** : La personnalité évolue progressivement basée sur les interactions et les préférences utilisateur
- **Rapports de personnalité** : Visualisation des traits actuels et de leur évolution

## Modèle de confiance et prérequis réseau

### Installation mono-utilisateur

Jarvis est conçu comme une installation privée mono-utilisateur. Toute entité ayant accès à l'API Jarvis est considérée comme pleinement autorisée à agir avec les privilèges du compte Windows utilisateur sur lequel Jarvis s'exécute.

### Périmètre réseau attendu

L'accès distant à Jarvis est intentionnel et doit passer par le réseau privé Tailscale de l'utilisateur :

- L'API Jarvis ne doit jamais être exposée publiquement sur Internet.
- Tailscale est le périmètre réseau attendu pour l'accès distant.
- Une compromission du compte Tailscale autorisé doit être considérée comme une compromission de l'accès à Jarvis.

### Recommandations opérationnelles

Pour sécuriser l'installation Jarvis :

- **Pare-feu Windows** : Restreindre l'accès au port 8000 à l'interface/réseau Tailscale lorsque possible.
- **Contrôle des appareils** : Surveiller et contrôler les appareils et sessions autorisés sur le tailnet.
- **Confidentialité des URLs** : Ne pas partager les URLs d'instances Jarvis avec des tiers.
- **Mises à jour** : Garder Python, les dépendances et Jarvis à jour selon le mécanisme documenté dans `bootstrap/update.ps1`.
- **Sécurité du poste** : Protéger le poste Windows puisque Jarvis agit sous le compte connecté.

### Mode Stark

Le Mode Stark est une fonctionnalité volontairement autonome :

- Il peut exécuter des actions sans confirmations interactives supplémentaires.
- Il ne doit être utilisé que pour des objectifs dont l'utilisateur accepte les effets.
- Il reste soumis à l'autorité de l'utilisateur propriétaire de l'installation.

### Mécanisme de démarrage

Le mécanisme de démarrage de référence est la tâche planifiée Windows `JarvisAgent` :

- Elle s'exécute à l'ouverture de session avec les permissions du compte utilisateur.
- Elle lance `uvicorn api.server:app --host 0.0.0.0 --port 8000`.
- Le service Windows historique `JarvisService` est abandonné car ses permissions ne permettent pas le fonctionnement attendu de Jarvis.

## Capacités principales

### Recherche web avancée

Jarvis dispose désormais de capacités de recherche web avancée, similaires à celles de Claude dans Chrome :

- **rechercher_web(requete, nombre_resultats)** : Effectue une recherche web via DuckDuckGo et retourne les résultats
- **analyser_page_web(url)** : Analyse et extrait le contenu d'une page web spécifique
- **rechercher_et_analyser(requete, nombre_pages)** : Combine recherche et analyse approfondie des pages pertinentes
- **extraire_informations_cles(texte)** : Extrait automatiquement les informations clés (URLs, emails, nombres, dates) d'un texte
- **synthetiser_resultats(resultats)** : Synthétise plusieurs résultats en un résumé cohérent

Ces outils permettent à Jarvis de :
- Rechercher des informations en ligne en temps réel
- Analyser le contenu de pages web
- Extraire et structurer automatiquement les informations importantes
- Synthétiser des résultats provenant de plusieurs sources

**Note** : La recherche web utilise DuckDuckGo qui ne nécessite pas de clé API. Le module inclut une limitation de taux pour respecter les politiques d'utilisation.

### Navigation interactive

Jarvis dispose désormais de capacités de navigation interactive complètes, similaires à Claude dans Chrome :

- **naviguer_vers(url, headless)** : Navigue vers une URL spécifique
- **cliquer_element(selector, url, headless)** : Clique sur un élément de la page
- **remplir_formulaire(selector, valeur, url, headless)** : Remplit un champ de formulaire
- **extraire_texte_page(selector, url, headless)** : Extrait le texte d'un élément ou de la page
- **prendre_capture(path, url, full_page, headless)** : Prend une capture d'écran de la page
- **executer_sequence(actions, headless)** : Exécute une séquence complexe d'actions
- **obtenir_infos_page(url, headless)** : Obtient des informations détaillées sur la page

Ces outils utilisent **Playwright**, choisi pour sa légèreté et ses performances optimales, permettant à Jarvis de :
- Naviguer de manière interactive sur les sites web
- Cliquer sur des boutons, liens et éléments interactifs
- Remplir et soumettre des formulaires
- Prendre des captures d'écran des pages
- Exécuter des séquences d'actions complexes
- Interagir avec du contenu JavaScript dynamique

**Installation requise** : Pour utiliser ces fonctionnalités, installez Playwright :
```powershell
pip install playwright
playwright install
```

**Note** : Par défaut, le navigateur s'exécute en mode headless (sans interface graphique) pour optimiser les ressources. Le mode avec interface est disponible en définissant `headless=False`.

### Sessions de navigation parallèles

Jarvis dispose désormais de capacités de sessions parallèles, similaire à Claude dans Chrome :

- **demarrer_overlay_navigation()** : Démarre l'interface visuelle de navigation en temps réel
- **arreter_overlay_navigation()** : Arrête l'interface visuelle de navigation
- **creer_session_navigation(session_id, headless)** : Crée une nouvelle session de navigation parallèle
- **naviguer_session(session_id, url)** : Navigue vers une URL dans une session spécifique (non-bloquant)
- **cliquer_session(session_id, selector)** : Clique sur un élément dans une session (non-bloquant)
- **remplir_session(session_id, selector, valeur)** : Remplit un champ dans une session (non-bloquant)
- **capture_session(session_id)** : Prend une capture d'écran dans une session (non-bloquant)
- **executer_js_session(session_id, script)** : Exécute du JavaScript dans une session (non-bloquant)
- **fermer_session(session_id)** : Ferme une session de navigation
- **lister_sessions()** : Liste toutes les sessions actives avec leur état
- **obtenir_etat_session(session_id)** : Obtient l'état détaillé d'une session spécifique

Ces outils permettent à Jarvis de :
- Gérer plusieurs sessions de navigation en parallèle
- Naviguer de manière non-bloquante (Jarvis continue à travailler pendant la navigation)
- Visualiser l'état des sessions en temps réel via l'overlay
- Exécuter des actions complexes sur plusieurs sites simultanément
- Intégrer parfaitement avec le système événementiel de Jarvis

**Fonctionnement comme Claude** : Les sessions sont non-bloquantes, Jarvis peut lancer une navigation et continuer à analyser/discuter pendant que le navigateur travaille en arrière-plan. L'overlay visuel montre l'état de toutes les sessions en temps réel.

### Overlay de navigation

Jarvis dispose d'un overlay visuel dédié à la navigation web :

- **Interface temps réel** : Affichage de l'état de toutes les sessions de navigateur actives
- **États visuels distincts** : IDLE (●), NAVIGATING (◉), LOADING (◌), INTERACTING (◈), ERROR (⚠), CLOSED (○)
- **Informations détaillées** : URL actuelle, titre de page, nombre d'actions, statut de capture d'écran
- **Gestion des erreurs** : Affichage des messages d'erreur directement dans l'overlay
- **Interface non-intrusive** : Fenêtre flottante avec transparence, positionnement configurable
- **Démarrage automatique** : S'intègre avec JarvisAgent pour démarrage automatique

**Activation** :
```python
demarrer_overlay_navigation()
```

**Arrêt** :
```python
arreter_overlay_navigation()
```

- Assistant conversationnel local avec mémoire persistante.
- Exécution d'outils réels via `tools.OUTILS`.
- Conscience dynamique des capacités grâce à l'inventaire temps réel de `core/tool_signatures.py`.
- Mode Stark pour les objectifs multi-étapes avec grammaire `>>`, `&&`, `||`.
- Mode action one-shot avec `!a`.
- API FastAPI sur le port `8000`.
- Streaming SSE pour afficher les événements intermédiaires en direct.
- Interface Tkinter locale dans `gui/app.py`.
- Interface web multi-device servie par FastAPI dans `gui/web/index.html`.
- Tâche planifiée `JarvisAgent` capable de lancer automatiquement `uvicorn api.server:app` dans la session utilisateur.
- Mémoire, rappels, automatisations, surveillance de dossiers, stockage, commandes shell/PowerShell et commandes personnalisées.
- **Interface vocale** : reconnaissance vocale via wake word ("Hey Jarvis") ou double-clap, synthèse vocale (TTS) pour les réponses.
- **Overlay visuel vocal** : indicateur flottant HUD affichant l'état vocal (ÉCOUTE, RÉFLEXION, PAROLE, ERREUR) en temps réel.
- **Suggestions contextuelles** : génération proactive de suggestions basées sur les patterns comportementaux, l'état système et le contexte utilisateur.
- **Analyse de performance** : auto-réflexion sur les décisions, détection de patterns d'erreur, apprentissage des solutions réussies.
- **Recherche sémantique** : indexation et recherche dans l'historique des interactions avec analyse thématique.
- **Recherche web avancée** : recherche web intelligente via DuckDuckGo, analyse de contenu de pages, extraction d'informations clés et synthèse de résultats.
- **Navigation interactive** : automatisation de navigateur via Playwright pour naviguer, cliquer, remplir des formulaires, prendre des captures d'écran et exécuter des séquences d'actions complexes.
- **Sessions parallèles** : gestion de multiples sessions de navigation en parallèle avec interface visuelle temps réel, similaire à Claude dans Chrome.
- **Overlay de navigation** : interface visuelle flottante montrant l'état des sessions de navigateur en temps réel.
- **Surveillance système** : monitoring continu CPU, mémoire, disque, réseau avec détection d'anomalies.
- **Personnalité adaptative** : traits de personnalité ajustables (sarcasme, formalité, proactivité, humour, empathie, concision, créativité) avec évolution basée sur les interactions.
- **Modèle souverain Jarvis-GC** : modèle local optimisé CPU/AVX2 basé sur Qwen 2.5 (1.5B/3B/7B) pour fonctionnement hors-ligne avec intelligence maximale.

### Surfaces utilisateur

| Surface | Fichier | Usage |
| --- | --- | --- |
| Console Rich | `jarvis.py` | Utilisation terminal complète |
| API FastAPI | `api/server.py` | Intégration locale, web, multi-device |
| Interface Tkinter | `gui/app.py` | Client desktop local consommant le SSE |
| Interface web | `gui/web/index.html` | Client navigateur servi sur `/web` |
| Tâche planifiée Windows | `JarvisAgent` | Démarrage automatique de l'API dans la session utilisateur |

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
- `pywin32` pour le service Windows historique (désactivé par l'installation)
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

Pour les fonctionnalités de navigation interactive (Playwright) :

```powershell
pip install playwright
playwright install
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

Jarvis utilise une cascade intelligente de providers LLM pour garantir réactivité et intelligence :

- **Modèle Souverain Jarvis-GC** (The Great Corporation) : Modèle local optimisé CPU/AVX2 basé sur Qwen 2.5, premier choix hors-ligne
- **Groq** via `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, etc. : Cloud ultra-rapide (120B paramètres)
- **OpenRouter** via `OPENROUTER_API_KEY` : Cloud alternatif (70B paramètres)
- **Ollama local** avec `qwen2.5:7b` : Fallback standard

Exemple PowerShell :

```powershell
$env:GROQ_API_KEY="votre_cle"
$env:OPENROUTER_API_KEY="votre_cle"
```

Pour le modèle souverain Jarvis-GC :

```powershell
ollama serve
ollama create jarvis-gc -f models/jarvis_gc/Modelfile
```

Pour Ollama fallback :

```powershell
ollama serve
ollama pull qwen2.5:7b
```

**Architecture de cascade** : Jarvis essaie d'abord les providers cloud (Groq/OpenRouter) pour réactivité maximale, puis le modèle souverain Jarvis-GC hors-ligne, et enfin le fallback local standard.

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

### 5. Tâche planifiée Windows `JarvisAgent`

La tâche `JarvisAgent` lance automatiquement :

```text
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Caractéristiques :

- Elle s'exécute dans la session de l'utilisateur Windows connecté, avec les mêmes permissions que le CLI, l'interface web et Tkinter.
- Elle lance uniquement `uvicorn api.server:app` ; `jarvis.cmd` reste le lancement direct du CLI.
- Le service historique `JarvisService`, exécuté sous `LocalSystem`, est désactivé par `bootstrap/install.ps1` s'il existe déjà.

Installation :

```powershell
cd %USERPROFILE%\Jarvis
PowerShell -ExecutionPolicy Bypass -File bootstrap\install.ps1 -GitHubPAT <votre_pat>
```

Démarrage :

```powershell
Start-ScheduledTask -TaskName JarvisAgent
```

Arrêt :

```powershell
Stop-ScheduledTask -TaskName JarvisAgent
```

Suppression :

```powershell
Unregister-ScheduledTask -TaskName JarvisAgent -Confirm:$false
```

### Configuration du démarrage automatique

`bootstrap/install.ps1` configure `JarvisAgent` pour démarrer à l'ouverture de session de l'utilisateur installé. Aucune élévation ni exécution sous `LocalSystem` n'est utilisée au lancement.

### Vérification de l'état de la tâche

Vérifier la tâche :

```powershell
Get-ScheduledTask -TaskName JarvisAgent | Select-Object TaskName, State
```

Attendu :
```
TaskName    State
--------    -----
JarvisAgent Running
```

Tester l'API :

```powershell
curl.exe "http://localhost:8000/jarvis/status"
```

Attendu : JSON avec CPU, RAM et active status.

Redémarrage :

```powershell
Stop-ScheduledTask -TaskName JarvisAgent
Start-ScheduledTask -TaskName JarvisAgent
```


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
| `provider` | `{"provider": "Groq", "model": "openai/gpt-oss-120b"}` | Provider LLM utilisé |
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

1. Arrêt et suppression du service Windows historique JarvisService, s'il existe (sc.exe)
2. Suppression des tâches planifiées JarvisAgent et JarvisAutoUpdate (PowerShell)
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
├── stark_session.py
├── voice_state.py
├── voice_overlay.py
├── autodestruct.py
├── contextual_suggestions.py
├── decision_analyzer.py
├── error_classification.py
├── pattern_analyzer.py
├── semantic_search.py
├── system_monitor.py
├── personality.py
├── translator.py
├── paths.py
└── confirmations.py

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
├── watchers.py
├── voice_input.py
├── voice_output.py
├── clap_input.py
├── calendar_integration.py
├── email_integration.py
├── web_search.py
└── browser_automation.py
```

### Responsabilités

- `core/intellect.py` : seul composant qui raisonne.
- `jarvis.py` : orchestration, modes, exécution, EventBus, agent autonome.
- `tools.py` : façade publique des outils.
- `capabilities/` : exécution déterministe.
- `api/server.py` : transport HTTP/SSE et fichiers statiques.
- `gui/app.py` et `gui/web/index.html` : présentation.
- `JarvisAgent` : tâche planifiée Windows exécutée dans la session utilisateur.

### Nouveaux modules core

- `core/voice_state.py` : Gestion de l'état vocal global (IDLE, LISTENING, THINKING, SPEAKING, ERROR) avec communication via fichier JSON partagé pour l'overlay
- `core/voice_overlay.py` : Overlay visuel flottant Tkinter affichant l'état vocal en temps réel avec style HUD
- `core/autodestruct.py` : Auto-destruction complète de Jarvis (service, tâches planifiées, variables d'environnement, dossier)
- `core/contextual_suggestions.py` : Génération de suggestions intelligentes basées sur patterns, état système, contexte utilisateur et automatisations potentielles
- `core/decision_analyzer.py` : Auto-réflexion sur les décisions, détection de patterns d'erreur, apprentissage des solutions réussies
- `core/error_classification.py` : Classification mécanique des erreurs système avec catégories prédéfinies
- `core/pattern_analyzer.py` : Détection et analyse des patterns comportementaux (horaires, actions répétitives, séquences)
- `core/semantic_search.py` : Indexation et recherche sémantique dans l'historique des interactions avec analyse thématique
- `core/system_monitor.py` : Surveillance continue de l'état système (CPU, mémoire, disque, réseau) avec détection d'anomalies
- `core/personality.py` : Gestion et adaptation de la personnalité Jarvis avec traits ajustables et évolution automatique

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
- **Vocal** : `activer_vocal()`, `desactiver_vocal()`, `lire_etat_vocal()`, `configurer_vocal()`.
- **Système** : `obtenir_etat_systeme()`, `generer_rapport_systeme()`, `detecter_anomalies()`.
- **Intelligence** : `generer_suggestions_contextuelles()`, `analyser_decisions_recentes()`, `rechercher_semantique()`.
- **Recherche web** : `rechercher_web()`, `analyser_page_web()`, `rechercher_et_analyser()`, `extraire_informations_cles()`, `synthetiser_resultats()`.
- **Navigation interactive** : `naviguer_vers()`, `cliquer_element()`, `remplir_formulaire()`, `extraire_texte_page()`, `prendre_capture()`, `executer_sequence()`, `obtenir_infos_page()`.
- **Personnalité** : `obtenir_personnalite()`, `ajuster_personnalite()`, `generer_rapport_personnalite()`.

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

Pour le démarrage automatique, consulter l'historique de la tâche `JarvisAgent` dans le Planificateur de tâches Windows. Le service Windows historique ne produit des logs dans `service/` que s'il a été activé manuellement.

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

Résultat de la dernière vérification : `69 tests passants` (57 tests rapides + 12 tests lents).

### Tests de recherche web

Tests spécifiques pour les fonctionnalités de recherche web :

- `tests/test_web_search.py` : Tests du moteur de recherche, extraction d'informations, et synthèse de résultats

### Tests de navigation interactive

Tests spécifiques pour les fonctionnalités de navigation interactive :

- `tests/test_browser_automation.py` : Tests de l'automatisation de navigateur, séquences d'actions, et gestion des erreurs

### Tests vocaux et overlay

Tests spécifiques pour les fonctionnalités vocales :

- `tests/test_voice_input.py` : Tests de reconnaissance vocale et wake word
- `tests/test_voice_output.py` : Tests de synthèse vocale (TTS)
- `tests/test_voice_state.py` : Tests de gestion de l'état vocal
- `tests/test_voice_overlay.py` : Tests de l'overlay visuel vocal
- `tests/test_clap_input.py` : Tests de détection de double-clap

### Tests manuels

Le dossier `tests/manual/` contient des tests nécessitant une intervention humaine :

- `test_overlay_direct.py` : Test direct de l'overlay sans uvicorn
- `test_overlay_manuel.py` : Test manuel des transitions d'état de l'overlay

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

Cause probable : la tâche `JarvisAgent` ou le serveur manuel tourne encore avec une ancienne version du code.

Solution :

```powershell
Stop-ScheduledTask -TaskName JarvisAgent
Start-ScheduledTask -TaskName JarvisAgent
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

### La tâche `JarvisAgent` refuse de démarrer

Vérifier :

- l'action avec `Get-ScheduledTask -TaskName JarvisAgent | Select-Object -ExpandProperty Actions`;
- que Python, `fastapi` et `uvicorn` sont installés pour le Python configuré;
- que le port `8000` n'est pas déjà occupé;
- l'historique de la tâche dans le Planificateur de tâches Windows.

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
