# Premier lancement - Guide de prise en main Jarvis

Ce guide vous accompagne lors de la première installation et configuration de Jarvis sur votre machine Windows.

## Prérequis

### Environnement système

- **OS** : Windows 10 ou 11
- **Python** : Python 3.12 recommandé (chemin détecté automatiquement par le script d'installation)
- **Dossier projet** : `%USERPROFILE%\Jarvis` (configurable via paramètre d'installation)

### Vérification de Python

Ouvrez PowerShell et vérifiez votre installation Python :

```powershell
python --version
```

Si Python n'est pas installé, téléchargez-le depuis [python.org](https://www.python.org/downloads/) et installez-le avec l'option "Add Python to PATH".

## Étape 1 - Clonage ou téléchargement du projet

Si vous avez accès au dépôt GitHub privé :

```powershell
cd %USERPROFILE%
git clone <url-du-repo> Jarvis
cd Jarvis
```

Sinon, placez simplement le dossier Jarvis dans `%USERPROFILE%\`.

## Étape 2 - Installation des dépendances

### Méthode recommandée : via requirements.txt

```powershell
cd %USERPROFILE%\Jarvis
python -m pip install -r requirements.txt
```

### Installation manuelle des dépendances principales

Si `requirements.txt` est incomplet ou pour une installation minimale :

```powershell
cd %USERPROFILE%\Jarvis
python -m pip install fastapi uvicorn requests pywin32 psutil rich ollama groq plyer
```

### Avec le chemin Python explicite (si nécessaire)

```powershell
& "C:\Program Files\Python312\python.exe" -m pip install -r requirements.txt
```

## Étape 3 - Configuration des providers LLM

Jarvis peut utiliser plusieurs providers LLM. Configurez au moins un d'entre eux.

### Option 1 - Groq (recommandé pour la rapidité)

1. Créez un compte sur [Groq](https://console.groq.com/)
2. Obtenez votre API key
3. Configurez la variable d'environnement :

```powershell
# Temporaire (session PowerShell actuelle)
$env:GROQ_API_KEY="votre_cle_groq"

# Permanente (niveau utilisateur)
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'votre_cle_groq', [System.EnvironmentVariableTarget]::User)

# Pour plusieurs clés (rotation automatique)
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY_1', 'cle_1', [System.EnvironmentVariableTarget]::User)
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY_2', 'cle_2', [System.EnvironmentVariableTarget]::User)
```

### Option 2 - OpenRouter

1. Créez un compte sur [OpenRouter](https://openrouter.ai/)
2. Obtenez votre API key
3. Configurez la variable d'environnement :

```powershell
$env:OPENROUTER_API_KEY="votre_cle_openrouter"
```

### Option 3 - Ollama (local, gratuit)

1. Téléchargez et installez [Ollama](https://ollama.ai/)
2. Lancez Ollama :

```powershell
ollama serve
```

3. Dans une autre fenêtre PowerShell, téléchargez le modèle recommandé :

```powershell
ollama pull qwen2.5:7b
```

Ollama sera utilisé automatiquement en fallback si Groq et OpenRouter ne sont pas configurés.

## Modèles vocaux locaux (optionnel)

Le mode vocal ne télécharge aucun modèle automatiquement. Téléchargez les fichiers suivants,
puis placez-les dans les dossiers indiqués (le dossier `models/` est ignoré par Git) :

- Vosk français : `models/vosk-model-small-fr-0.22/`
- Vosk anglais : `models/vosk-model-small-en-us-0.15/`
- Piper français : `models/piper/fr_FR-siwis-low.onnx` et
  `models/piper/fr_FR-siwis-low.onnx.json`
  ([téléchargement officiel](https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR/siwis/low))
- Piper anglais : `models/piper/en_US-lessac-low.onnx` et
  `models/piper/en_US-lessac-low.onnx.json`
  ([téléchargement officiel](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/low))

Pour un essai matériel des écouteurs, lancez :

```powershell
python scripts/manuel_voix.py
```

## Fonctionnalités vocales et overlay

### Activation de l'interface vocale

Une fois les modèles vocaux installés, vous pouvez activer l'interface vocale :

```powershell
# Dans la console Jarvis
Jarvis, active le vocal
```

Ou via l'outil :

```powershell
activer_vocal()
```

### Wake word et double-clap

Jarvis supporte deux modes d'activation vocale :

- **Wake word** : Dites "Hey Jarvis" pour activer l'écoute
- **Double-clap** : Faites deux claques rapides pour activer l'écoute alternative

### Overlay visuel vocal

L'overlay visuel s'affiche automatiquement lors du démarrage de JarvisAgent :

- **ÉCOUTE** (cyan) : Jarvis écoute votre commande
- **RÉFLEXION** (orange) : Jarvis traite votre demande
- **PAROLE** (cyan) : Jarvis répond à voix haute
- **ERREUR** (rouge) : Une erreur vocale s'est produite
- **IDLE** : L'overlay est masqué

L'overlay est non-intrusif : il ne bloque pas les clics et ne vole pas le focus.

### Test de l'overlay

Pour tester l'overlay sans démarrer Jarvis complet :

```powershell
python tests\manual\test_overlay_direct.py
```

## Étape 4 - Premier lancement via script

### Lancement console (interface terminal)

```powershell
cd %USERPROFILE%\Jarvis
python jarvis.py
```

Ou utilisez le raccourci Windows si présent :

```powershell
jarvis.cmd
```

Note : `jarvis.cmd` utilise le chemin dynamique du script, il fonctionne quel que soit l'emplacement d'installation.

**Test de base** : Tapez "Bonjour Jarvis" et vérifiez que vous recevez une réponse.

### Lancement serveur API (pour interfaces web/Tkinter)

```powershell
cd %USERPROFILE%\Jarvis
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Une fois lancé, vous pouvez :
- Accéder à l'interface web : http://localhost:8000/web
- Voir la documentation API : http://localhost:8000/docs
- Tester le statut : http://localhost:8000/jarvis/status

### Lancement interface Tkinter

**Important** : Le serveur API doit déjà tourner.

Dans une nouvelle fenêtre PowerShell :

```powershell
cd %USERPROFILE%\Jarvis
python gui\app.py
```

## Étape 5 - Lancement manuel (sans script)

### Console manuelle

```powershell
cd %USERPROFILE%\Jarvis
python jarvis.py
```

### API manuelle

```powershell
cd %USERPROFILE%\Jarvis
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

### Tkinter manuelle

```powershell
cd %USERPROFILE%\Jarvis
python gui\app.py
```

## Étape 6 - Tests de validation

### Test 1 - API statut

```powershell
curl.exe "http://localhost:8000/jarvis/status"
```

Résultat attendu :

```json
{
  "cpu": 12.5,
  "ram": 48.2,
  "active": true
}
```

### Test 2 - API conversation simple

```powershell
curl.exe -X POST "http://localhost:8000/jarvis/ask" `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"bonjour\"}"
```

### Test 3 - API streaming

```powershell
curl.exe -N "http://localhost:8000/jarvis/stream?message=bonjour"
```

### Test 4 - Interface web

Ouvrez votre navigateur et accédez à :

```
http://localhost:8000/web
```

Testez l'envoi d'un message et vérifiez que la réponse s'affiche correctement.

## Étape 7 - Tâche planifiée `JarvisAgent` (optionnel)

Pour démarrer automatiquement Jarvis à l'ouverture de votre session Windows, utilisez `JarvisAgent`. Elle lance :

```powershell
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Elle s'exécute sous le compte de la session Windows, ce qui garantit les mêmes permissions pour CLI, Web et Tkinter. Le service historique `JarvisService` est désactivé par l'installation s'il existe.

### Démarrage, arrêt et vérification

```powershell
Start-ScheduledTask -TaskName JarvisAgent
Get-ScheduledTask -TaskName JarvisAgent | Select-Object TaskName, State
Stop-ScheduledTask -TaskName JarvisAgent
```

## Étape 8 - Configuration multi-instance (optionnel)

Si vous avez plusieurs machines Jarvis sur votre réseau via Tailscale :

### Installation de Tailscale

1. Téléchargez et installez [Tailscale](https://tailscale.com/)
2. Connectez-vous à votre tailnet

### Ajout d'instances distantes

Depuis l'interface web ou Tkinter :
1. Cliquez sur le bouton ⚙ (Gérer les instances)
2. Activez "Découverte réseau Tailscale"
3. Sélectionnez l'appareil détecté et cliquez "Ajouter"
4. L'instance distante apparaît dans le sélecteur

### Test de l'instance distante

1. Sélectionnez l'instance distante dans le sélecteur
2. Envoyez un message
3. Vérifiez que la réponse provient bien de l'instance distante

## Sécurité et modèle de confiance

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

Pour plus de détails sur le modèle de confiance et les hypothèses de sécurité, consultez `ARCHITECTURE.md`.

## Dépannage du premier lancement

### Erreur "ModuleNotFoundError"

**Cause** : Une dépendance n'est pas installée.

**Solution** :

```powershell
python -m pip install <nom_du_module_manquant>
```

### Erreur "Port 8000 already in use"

**Cause** : Le port 8000 est déjà utilisé par une autre application.

**Solution** :
- Arrêtez l'application qui utilise le port 8000
- Ou utilisez un autre port :

```powershell
python -m uvicorn api.server:app --host 0.0.0.0 --port 8001
```

### Erreur "Tailscale non disponible"

**Cause** : Tailscale n'est pas installé ou non connecté.

**Solution** :
- Installez Tailscale
- Connectez-vous à votre tailnet
- Vérifiez avec `tailscale status`

### Jarvis ne répond pas

**Vérifications** :
1. Un provider LLM est-il configuré ? (Groq, OpenRouter ou Ollama)
2. Les variables d'environnement sont-elles correctes ?
3. Le firewall bloque-t-il la connexion ?
4. Testez avec Ollama en local si les providers cloud échouent

### La tâche `JarvisAgent` refuse de démarrer

**Vérifications** :
1. Consultez l'action et l'historique dans le Planificateur de tâches Windows
2. Vérifiez que Python est installé et détecté par le script d'installation
3. Vérifiez que les dépendances sont installées pour ce Python
4. Vérifiez que le port `8000` n'est pas déjà occupé

## Prochaines étapes

Une fois Jarvis opérationnel :

1. **Explorez les capacités** : Demandez "Jarvis, qu'est-ce que tu peux faire ?"
2. **Testez le Mode Stark** : Essayez `!S audite le stockage >> liste les gros fichiers`
3. **Configurez les rappels** : "Ajoute un rappel pour demain à 9h"
4. **Activez la surveillance** : "Surveille le dossier Downloads"
5. **Lisez la documentation complète** : `README.md`, `ARCHITECTURE.md`, `EXECUTION_OUTILS.md`

## Support

En cas de problème persistant :

1. Consultez le fichier `README.md` pour la documentation complète
2. Vérifiez l'historique de `JarvisAgent` dans le Planificateur de tâches si la tâche est utilisée
3. Testez chaque composant isolément (console, API, web, Tkinter)
4. Vérifiez les variables d'environnement avec :

```powershell
Get-ChildItem Env:
```

## Résumé rapide

1. Installer Python 3.12
2. Cloner/télécharger Jarvis dans `%USERPROFILE%\Jarvis`
3. Installer les dépendances : `python -m pip install -r requirements.txt`
4. Configurer un provider LLM (Groq recommandé)
5. Lancer : `python jarvis.py` ou `python -m uvicorn api.server:app`
6. Tester l'interface web : http://localhost:8000/web
7. (Optionnel) Configurer la tâche `JarvisAgent` pour démarrage automatique

Bienvenue dans Jarvis, votre assistant IA local !
