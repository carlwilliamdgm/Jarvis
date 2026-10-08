# Installation sur machine vierge - Guide automatisé

Ce guide détaille l'installation complète de GreatOS/Jarvis sur une machine Windows vierge à l'aide du script d'installation automatisé.

## Prérequis

- **OS** : Windows 10 ou 11 (64 bits)
- **Permissions** : Droits administrateur requis pour l'installation
- **Accès réseau** : Connexion internet pour télécharger les dépendances
- **GitHub PAT** : Personal Access Token GitHub avec scope `repo` pour cloner le dépôt privé

## Méthode 1 (Recommandée) : Installation en une commande via install.ps1

Si vous disposez du dépôt cloné ou décompressé :

### Sous Windows :
Dans un terminal PowerShell avec privilèges Administrateur à la racine du projet :
`powershell
.\install.ps1
`
*Le script détecte Python, crée le virtualenv .venv, installe les dépendances, génère un .env sécurisé si absent, configure Ollama/Jarvis-GC et enregistre la tâche planifiée JarvisAgent pour un démarrage automatique silencieux de l'API.*

Alternativement, vous pouvez faire un **double-clic sur Setup.cmd** à la racine pour déclencher l'installation.

### Sous Linux / macOS :
`ash
./install.sh
`

## Méthode 2 : Téléchargement du script public d'amorçage

Si vous êtes sur une machine totalement vierge sans le dépôt :
```powershell
# Télécharger le script depuis GitHub
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/carlwilliamdgm/Jarvis/main/install_public.ps1" -OutFile "$env:TEMP\install_public.ps1"

# Exécuter en tant qu'Administrateur
powershell.exe -ExecutionPolicy Bypass -File "$env:TEMP\install_public.ps1"
```

### Le script effectuera automatiquement :

1. **Détection/Installation de Python 3.12**
   - Cherche Python 3.12 dans les emplacements standards
   - Le télécharge et l'installe automatiquement si absent

2. **Détection/Installation de Git**
   - Vérifie la présence de Git
   - L'installe automatiquement via Git for Windows si absent

3. **Clonage du dépôt Jarvis**
   - Clone le dépôt privé dans `%USERPROFILE%\Jarvis` (par défaut)
   - Accepte un paramètre `-InstallDir` pour un emplacement personnalisé
   - Le PAT GitHub est utilisé de manière sécurisée (jamais stocké dans .git/config)

4. **Installation des dépendances Python**
   - Exécute `pip install -r requirements.txt`
   - Installe toutes les dépendances avec versions bornées

5. **Configuration des clés API**
   - Demande les clés Groq API (1 à 5 clés, minimum 1 requise)
   - Demande la clé OpenRouter (optionnelle)
   - Stocke les clés au niveau Machine (variables d'environnement)

6. **Installation d'Ollama**
   - Télécharge et installe Ollama automatiquement
   - Télécharge le modèle qwen2.5:7b (fallback local)

7. **Configuration de la tâche planifiée JarvisAgent**
   - Désactive le service Windows historique (JarvisService)
   - Crée la tâche planifiée JarvisAgent qui lance l'API au démarrage de session
   - S'exécute dans la session utilisateur interactive (accès matériel complet)

8. **Stockage du PAT pour mises à jour futures**
   - Stocke le PAT dans `GIT_PAT_JARVIS` (Machine-level)
   - Utilisé par `bootstrap/update.ps1` pour les mises à jour automatiques

### Installation avec emplacement personnalisé

```powershell
powershell.exe -ExecutionPolicy Bypass -File bootstrap\install.ps1 -GitHubPAT "votre_pat" -InstallDir "D:\GreatOS"
```

## Méthode manuelle (alternative)

Si vous préférez une installation manuelle :

### Étape 1 - Installer Python 3.12

Téléchargez depuis [python.org](https://www.python.org/downloads/) ou utilisez le Microsoft Store.

### Étape 2 - Installer Git

Téléchargez depuis [git-scm.com](https://git-scm.com/downloads)

### Étape 3 - Cloner le dépôt

```powershell
cd %USERPROFILE%
git clone https://github.com/carlwilliamdgm/Jarvis.git Jarvis
cd Jarvis
```

### Étape 4 - Installer les dépendances

```powershell
python -m pip install -r requirements.txt
```

### Étape 5 - Configurer les clés API

```powershell
# Groq (recommandé)
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY_1', 'votre_cle', [System.EnvironmentVariableTarget]::Machine)

# OpenRouter (optionnel)
[System.Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', 'votre_cle', [System.EnvironmentVariableTarget]::Machine)
```

### Étape 6 - Installer Ollama

```powershell
# Télécharger depuis https://ollama.ai/download
# Puis lancer :
ollama serve
ollama pull qwen2.5:7b
```

### Étape 7 - Configurer la tâche planifiée (optionnel)

Utilisez le script `update_scheduled_task.ps1` pour configurer JarvisAgent.

## Vérification de l'installation

### Vérifier que Jarvis fonctionne

```powershell
cd %USERPROFILE%\Jarvis
python greatos.py
```

### Vérifier l'API

Ouvrez un navigateur et accédez à :
- `http://localhost:8000` - API
- `http://localhost:8000/web` - Interface web
- `http://localhost:8000/docs` - Documentation FastAPI

### Vérifier la tâche planifiée

```powershell
Get-ScheduledTask -TaskName JarvisAgent
```

## Configuration du modèle souverain Jarvis-GC (optionnel)

Pour utiliser le modèle souverain local optimisé :

```powershell
ollama serve
ollama create jarvis-gc -f models/jarvis_gc/Modelfile
```

Variables d'environnement optionnelles :
```powershell
$env:JARVIS_GC_TIMEOUT="60"  # Timeout en secondes (défaut: 45)
$env:JARVIS_GC_THREADS="8"  # Nombre de threads (défaut: 4)
```

## Mise à jour de l'installation

Le script `bootstrap/update.ps1` met à jour automatiquement :

```powershell
cd %USERPROFILE%\Jarvis
powershell.exe -ExecutionPolicy Bypass -File bootstrap\update.ps1
```

Ce script :
- Effectue un `git pull` en utilisant le PAT stocké
- Met à jour les dépendances Python
- Redémarre la tâche planifiée si nécessaire

## Dépannage

### Python non trouvé après installation

Le script d'installation actualise automatiquement les variables d'environnement. Si vous avez des problèmes :

```powershell
# Redémarrer PowerShell ou exécuter :
$env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
```

### Ollama ne démarre pas

Vérifiez que le service Ollama est en cours d'exécution :
```powershell
Get-Service ollama
Start-Service ollama
```

### Tâche planifiée ne démarre pas

Vérifiez les logs dans `%USERPROFILE%\Jarvis\logs\uvicorn.log`

### Port 8000 déjà utilisé

Modifiez le port dans la tâche planifiée ou utilisez une autre machine virtuelle.

## Structure de l'installation

Après installation, la structure est :

```
%USERPROFILE%\Jarvis\
├── bootstrap\          # Scripts d'installation/mise à jour
├── context_engine\     # Moteur de contexte et profils
├── core_intellect\    # Cerveau LLM et planification
├── datashield\        # Sécurité et chiffrement
├── interface_morphique\ # API FastAPI et interfaces
├── jarvis\            # Agent principal et voix
├── learning\          # Apprentissage et profils utilisateurs
├── models\            # Modèles Ollama (exclus par git)
├── service\           # Service Windows (historique)
├── snapshots\         # Snapshots système (exclus par git)
├── syncsphere\        # Gestion des snapshots
├── taskflow\          # Outils et automatisations
├── tests\             # Suite de tests
├── greatos.py         # Point d'entrée CLI
├── requirements.txt   # Dépendances Python
└── .venv\             # Environnement virtuel (exclus par git)
```

## Profils utilisateurs

Le système de profils est automatique et dynamique :
- Le profil est créé automatiquement au premier lancement
- L'identifiant utilisateur est résolu via `getpass.getuser()` ou la variable `GREATOS_USER`
- Les profils sont stockés dans `learning/profiles/<user_id>/profile.json`
- Aucune configuration manuelle n'est nécessaire

## Sécurité

- Les clés API sont stockées au niveau Machine (non visibles par les autres utilisateurs)
- Le PAT GitHub est stocké dans `GIT_PAT_JARVIS` (Machine-level)
- Jarvis s'exécute avec les droits de l'utilisateur connecté (pas d'élévation UAC)
- L'API n'est pas sécurisée par défaut : utilisez `JARVIS_API_KEY` si accessible depuis le réseau

## Prochaines étapes

1. Consultez [PREMIER_LANCEMENT.md](PREMIER_LANCEMENT.md) pour la configuration détaillée
2. Consultez [README.md](README.md) pour l'utilisation quotidienne
3. Consultez [ETAT_DES_LIEUX.md](ETAT_DES_LIEUX.md) pour l'état actuel du projet
