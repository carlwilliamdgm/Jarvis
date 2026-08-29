# Configuration de la Recherche Web pour Jarvis

## Problème résolu

Le Mode Stark de Jarvis rencontrait des anomalies lors des recherches web :
- Boucles infinies sur des recherches infructueuses
- Épuisement du budget de décisions (5 décisions par micro-objectif)
- Résultats DuckDuckGo non pertinents ou vides

## Solution implémentée

### 1. duckduckgo-search (moteur principal - VRAIMENT GRATUIT)
- **100% gratuit, sans carte de crédit**
- Bibliothèque Python maintenue par la communauté
- Résultats fiables et régulièrement mis à jour
- Installation simple : `pip install duckduckgo-search`

### 2. Brave Search API (optionnel - payant avec crédits)
- **Nécessite une carte de crédit** pour l'inscription
- $5 de crédits mensuels (~1000 requêtes)
- Résultats structurés et fiables
- Uniquement si vous avez déjà un compte Brave

### 3. DuckDuckGo API classique (fallback)
- Parsing HTML amélioré avec plusieurs patterns
- Approche alternative si le parsing principal échoue
- Messages informatifs au lieu d'erreurs brutes

### 4. Détection d'échec Mode Stark
- Compteur spécifique pour les échecs de recherche web
- Abandon automatique après 2 échecs consécutifs
- Message clair à l'utilisateur en cas d'échec

## Configuration

### Option 1 : duckduckgo-search (RECOMMANDÉ - VRAIMENT GRATUIT)

1. **Installer la bibliothèque** :
   ```bash
   pip install duckduckgo-search
   ```
   
   **Si vous avez des problèmes d'installation** (problèmes de permissions, etc.) :
   - Essayez avec `python -m pip install --user duckduckgo-search`
   - Ou utilisez un environnement virtuel : `python -m venv venv && venv\Scripts\activate && pip install duckduckgo-search`

2. **Aucune configuration supplémentaire nécessaire** !
   - Jarvis détectera automatiquement la bibliothèque
   - Fonctionne immédiatement sans clé API
   - Mis à jour régulièrement par la communauté

### Option 2 : Brave Search API (OPTIONNEL - payant)

⚠️ **Note importante** : Brave Search API nécessite maintenant une carte de crédit pour l'inscription et n'est plus vraiment gratuit (seulement $5 de crédits mensuels).

1. **Créer un compte Brave Search API** :
   - Allez sur https://brave.com/search/api/
   - Créez un compte (carte de crédit requise)
   - Obtenez votre clé API

2. **Configurer la clé API** :
   ```bash
   # Sur Windows (PowerShell)
   setx BRAVE_API_KEY "votre_clé_api_ici"
   
   # Sur Linux/macOS
   export BRAVE_API_KEY="votre_clé_api_ici"
   # Ajoutez cette ligne à votre ~/.bashrc ou ~/.zshrc
   ```

3. **Redémarrer Jarvis** pour que la variable d'environnement soit prise en compte

### Sans aucune configuration (mode dégradé)

Sans duckduckgo-search ni clé API Brave, Jarvis utilisera DuckDuckGo classique :
- Résultats peuvent être moins fiables
- Possibilité d'échecs de parsing
- Messages informatifs en cas de problème

## Test de la configuration

```python
from capabilities.web_search import WebSearchEngine

engine = WebSearchEngine()
print("Provider actuel:", engine.preferred_provider)
print("Clé Brave configurée:", bool(engine.brave_api_key))

# Test de recherche
results = engine.search("Balabolka text to speech", 3)
print("Résultats:", results)
```

## Comparaison avec les autres assistants JARVIS

D'après l'analyse des projets open source :

| Assistant | Moteur de recherche | Avantages | Inconvénients |
|-----------|-------------------|-----------|---------------|
| **FRIDAY** | Brave Search API + DuckDuckGo fallback | Solution hybride robuste | Brave = carte de crédit requise |
| **Jarvis AI (atharva-shinde7)** | API cloud avec quota | Dépend de fournisseurs externes | Nécessite clés API |
| **open-websearch** | Multi-moteur (Bing, Baidu, DuckDuckGo, etc.) | Très flexible mais complexe | Installation complexe |
| **Notre Jarvis** | duckduckgo-search + DuckDuckGo amélioré + détection d'échec | **Vraiment gratuit sans carte de crédit** | Dépend de bibliothèque externe |

## Dépannage

### Problème : "Aucun résultat trouvé"
- Vérifiez votre connexion internet
- Essayez de configurer Brave Search API
- Reformulez votre requête de recherche

### Problème : Boucles en Mode Stark
- Le système détecte maintenant automatiquement les échecs
- Abandon après 2 échecs de recherche web consécutifs
- Vérifiez la configuration de votre clé API

### Problème : Messages d'erreur DuckDuckGo
- Normal sans clé API Brave
- Configurez BRAVE_API_KEY pour des résultats fiables
- Le système fonctionnera mieux avec Brave Search

## Maintenance

Les améliorations futures pourraient inclure :
- Support pour d'autres moteurs de recherche (Bing, Google)
- Cache local des résultats de recherche
- Pagination pour les recherches étendues
- Filtres par langue et région

---

**Note** : Cette configuration est basée sur l'analyse des meilleures pratiques des assistants IA open source existants comme FRIDAY, OpenJarvis et autres projets similaires.
