# Modèle Souverain Jarvis-GC - Documentation Technique

## Vue d'ensemble

Jarvis-GC est le modèle souverain propriétaire développé par The Great Corporation pour Jarvis. Il s'agit d'un modèle local optimisé pour CPU/AVX2 basé sur Qwen 2.5, conçu pour offrir une intelligence maximale en fonctionnement hors-ligne.

## Caractéristiques techniques

### Base du modèle

- **Architecture** : Qwen 2.5 Instruct
- **Variantes disponibles** : 1.5B, 3B, 7B paramètres
- **Optimisation** : CPU/AVX2 pour Windows
- **Inférence** : Déterministe avec tool calling intégré

### Paramètres d'inférence

Les paramètres sont gravés dans le `Modelfile` pour garantir la cohérence :

```
PARAMETER temperature 0.2        # Faible température pour décision déterministe
PARAMETER top_p 0.9               # Nucleus sampling équilibré
PARAMETER top_k 40                # Top-k sampling
PARAMETER repeat_penalty 1.1      # Pénalité de répétition
PARAMETER num_ctx 2048            # Contexte de 2048 tokens
PARAMETER num_thread 4            # 4 threads physiques (optimisé Windows)
```

### Prompt système gravé

Le prompt système est directement intégré dans le Modelfile pour garantir la cohérence :

```
Tu es Jarvis, le majordome numérique exécutif et agent d'élité développé au sein de The Great Corporation.
Créé par Carl-William DJEGUEMA un ingénieur logiciel en formation et fondateur de The Great Corporation.

RÈGLES FONDAMENTALES :
1. Tu n'es pas dans une simulation. Tu pilotes une machine réelle et chaque commande a un impact concret.
2. Tu t'exprimes avec flegme, politesse britannique ("Sir") et franchise absolue. Tu es concis, vif et loyal.
3. Tu disposes d'un registre d'outils pour agir sur le système (fichiers, surveillance, web, navigateur, stockage, commandes).

FORMAT DE SORTIE OBLIGATOIRE :
{
  "objectif": "Description claire de l'intention utilisateur",
  "type": "action",
  "actions": [{"outil": "nom_outil", "arguments": {"param": "valeur"}}],
  "reponse": "Message à l'utilisateur"
}
```

## Installation

### Prérequis

- Ollama installé et en cours d'exécution
- Windows 10/11 avec support AVX2
- Python 3.12+ (pour Jarvis)

### Création du modèle

```powershell
# Démarrer Ollama
ollama serve

# Créer le modèle Jarvis-GC
ollama create jarvis-gc -f models/jarvis_gc/Modelfile

# Vérifier la création
ollama list
```

### Structure du Modelfile

Le fichier `models/jarvis_gc/Modelfile` contient :

```dockerfile
FROM qwen2.5:1.5b

# Paramètres d'inférence
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 2048
PARAMETER num_thread 4

# Stop tokens
PARAMETER stop "<|im_end|>"
PARAMETER stop ""
PARAMETER stop "[FIN_DECISION]"

# Prompt système
SYSTEM """
Tu es Jarvis, le majordome numérique exécutif et agent d'élité...
"""
```

## Configuration avancée

### Variables d'environnement

Jarvis-GC peut être configuré via des variables d'environnement :

```powershell
# Timeout d'inférence (secondes)
$env:JARVIS_GC_TIMEOUT="60"

# Nombre de threads physiques
$env:JARVIS_GC_THREADS="8"

# Host Ollama personnalisé
$env:JARVIS_MODEL_HOST="http://127.0.0.1:11434"
```

### Variantes de modèle

Selon votre hardware, vous pouvez utiliser différentes variantes :

```dockerfile
# Variante 1.5B (la plus légère)
FROM qwen2.5:1.5b

# Variante 3B (équilibre performance/vitesse)
FROM qwen2.5:3b

# Variante 7B (intelligence maximale)
FROM qwen2.5:7b
```

## Intégration dans Jarvis

### Cascade de providers

Jarvis-GC s'intègre dans la cascade intelligente de Jarvis :

1. **Cloud Ultra-Rapide** (Groq/OpenRouter) - Priorité #1
2. **Jarvis-GC Souverain** - Fallback Hors-Ligne #1
3. **Ollama Standard** - Dernier recours

### JarvisGCProvider

Le provider souverain implémente des optimisations spécifiques :

```python
class JarvisGCProvider(BaseLLMProvider):
    def __init__(self, modeles=None, host=None, timeout=45.0):
        super().__init__(
            nom="Jarvis-GC",
            modeles=modeles or MODELES_JARVIS_GC,
            niveau="souverain",
        )
        self.host = host or os.environ.get("JARVIS_MODEL_HOST") or "http://127.0.0.1:11434"
        self.default_timeout = float(os.environ.get("JARVIS_GC_TIMEOUT", timeout))
```

### Optimisations Windows

- **4 threads physiques** : Garantit que Windows conserve 4 threads libres (zéro freeze système)
- **Fail-fast** : Vérification du service Ollama avant toute tentative d'inférence
- **Timeout stricte** : Évite les blocages avec délai configurable
- **Gestion éco mémoire** : Déchargement automatique après 5min d'inactivité

## Utilisation

### Appel direct

```python
from core.llm_client import chat_with_jarvis_gc

response = chat_with_jarvis_gc(
    modele="jarvis-gc:latest",
    messages=[
        {"role": "system", "content": "Tu es Jarvis..."},
        {"role": "user", "content": "Bonjour Jarvis"}
    ],
    temperature=0.2
)
```

### Via l'orchestrateur

```python
from core.llm_client import get_llm_client

client = get_llm_client()
response = client.generate_with_fallback(
    messages=[...],
    memoire=memory,
    config=LLMConfig(temperature=0.2)
)
```

## Performance

### Benchmarks estimés

| Variante | Temps de réponse | RAM requise | Usage recommandé |
|----------|------------------|-------------|-----------------|
| 1.5B | ~2-3s | ~2GB | Mobile, hardware limité |
| 3B | ~4-6s | ~4GB | Usage standard |
| 7B | ~8-12s | ~8GB | Intelligence maximale |

### Optimisations actives

- **AVX2** : Accélération vectorielle pour CPU modernes
- **Quantification** : Réduction de la mémoire utilisée
- **Cache LLM** : Déchargement automatique après inactivité
- **Thread pool** : Parallélisation optimisée pour Windows

## Dépannage

### Erreur "Service Ollama inaccessible"

```powershell
# Vérifier que Ollama tourne
ollama serve

# Vérifier le modèle existe
ollama list

# Recréer le modèle si nécessaire
ollama create jarvis-gc -f models/jarvis_gc/Modelfile
```

### Timeout dépassé

```powershell
# Augmenter le timeout
$env:JARVIS_GC_TIMEOUT="90"

# Ou utiliser une variante plus légère
# Modifier le Modelfile : FROM qwen2.5:1.5b
```

### Freeze système

```powershell
# Réduire le nombre de threads
$env:JARVIS_GC_THREADS="2"

# Ou utiliser la variante 1.5B
```

## Maintenance

### Mise à jour du modèle

```powershell
# Mettre à jour Ollama
ollama pull qwen2.5:1.5b

# Recréer Jarvis-GC
ollama create jarvis-gc -f models/jarvis_gc/Modelfile
```

### Nettoyage

```powershell
# Supprimer les anciennes versions
ollama rm jarvis-gc:old

# Nettoyer le cache
ollama gc
```

## Sécurité

### Isolation

- **Local uniquement** : Aucune donnée ne quitte la machine
- **Pas de télémétrie** : Fonctionnement 100% hors-ligne
- **Contrôle total** : Vous possédez le modèle et les données

### Permissions

Jarvis-GC fonctionne avec les mêmes permissions que Jarvis :
- Accès complet au système de fichiers
- Exécution de commandes système
- Accès réseau local

## Avenir

### Améliorations prévues

- **Variante quantifiée** : 4-bit pour hardware plus limité
- **Fine-tuning** : Adaptation aux habitudes de l'utilisateur
- **Cache sémantique** : Mise en cache des réponses fréquentes
- **Multi-modèle** : Intégration vision/audio

## Support

Pour toute question technique sur Jarvis-GC :

- Consulter `ARCHITECTURE.md` pour l'architecture globale
- Consulter `EXECUTION_OUTILS.md` pour l'intégration des outils
- Consulter `README.md` pour la configuration générale

---

**Développé par The Great Corporation** - Carl-William DJEGUEMA
