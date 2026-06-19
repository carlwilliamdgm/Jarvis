# Jarvis - Assistant IA Local

Jarvis est un assistant IA local-first en Python, inspiré de l'assistant de Tony Stark dans Iron Man. Développé par Carl-William DJEGUEMA (The Great Corporation), Jarvis est conçu pour être votre compagnon cognitif personnel, capable d'effectuer des actions concrètes sur votre machine tout en maintenant une personnalité engageante et sarcastique.

## 🎯 Caractéristiques Principales

- **Local-first** : Fonctionne principalement avec des modèles locaux (Ollama) ou cloud (Groq, OpenRouter)
- **Mode Stark** : Exécution autonome structurée avec grammaire spécifique (`>>`, `&&`, `||`)
- **Mode Action** : Commandes directes one-shot avec `!a`
- **Gestion de fichiers** : Création, lecture, suppression, organisation de dossiers
- **Audit de stockage** : Surveillance de l'espace disque avec alertes automatiques
- **Rappels et automatisations** : Planification de tâches récurrentes
- **Surveillance de dossiers** : Monitoring proactif de répertoires spécifiques
- **Commandes personnalisées** : Création de raccourcis pour vos commandes fréquentes
- **Mémoire persistante** : Conservation des notes, préférences et contexte entre les sessions
- **Interface API REST** : Intégration possible avec d'autres applications
- **Interface graphique** : Option GUI pour une utilisation plus conviviale
- **Service Windows** : Intégration en tant que service système

## 📋 Prérequis

- Python 3.12+
- Ollama (pour les modèles locaux) ou clés API pour Groq/OpenRouter
- Windows (support principal), Linux/macOS (support partiel)

## 🚀 Installation

1. Cloner le repository :
```bash
git clone https://github.com/carlwilliamdgm/Jarvis.git
cd Jarvis
```

2. Installer les dépendances :
```bash
pip install -r requirements.txt
```

3. Configurer les variables d'environnement (optionnel) :
```bash
# Pour Groq (support multi-clés)
export GROQ_API_KEY="votre_cle_1"
export GROQ_API_KEY_1="votre_cle_1"
export GROQ_API_KEY_2="votre_cle_2"

# Pour OpenRouter
export OPENROUTER_API_KEY="votre_cle"
```

4. Lancer Ollama (si utilisé) :
```bash
ollama serve
ollama pull qwen2.5:7b
```

## 💻 Utilisation

### Lancement Console

```bash
python jarvis.py
```

Sur Windows :
```bash
jarvis.cmd
```

### Modes d'Exécution

#### Mode Normal
Interagissez naturellement avec Jarvis :
```
Vous: Liste le contenu de mon dossier Downloads
Jarvis: Voici le contenu de votre dossier Downloads...
```

#### Mode Action One-Shot
Forcez une intention d'action pour le prochain message :
```
!a
Crée un dossier test dans Documents
```

#### Mode Stark
Exécution autonome structurée avec grammaire spécifique :
```
!S audite le stockage >> liste les gros fichiers && (notifie le résultat || note le résultat)
```

**Grammaire Stark :**
- `>>` : Macro-étapes séquentielles (arrêt si échec)
- `&&` : Dépendances gauche-droite dans un segment
- `||` : Alternatives/replis (première réussite retenue)

### Commandes Principales

#### Fichiers et Dossiers
- `lister_dossier(chemin)` : Liste le contenu d'un dossier
- `creer_dossier(chemin)` : Crée un nouveau dossier
- `creer_fichier(chemin, contenu)` : Crée un fichier avec contenu
- `lire_fichier(chemin)` : Lit le contenu d'un fichier
- `supprimer(chemin)` : Supprime un fichier ou dossier

#### Stockage
- `audit_stockage()` : Analyse l'espace disque disponible
- `top_fichiers_lourds(n)` : Liste les plus gros fichiers
- `vider_temp()` : Nettoie les fichiers temporaires
- `vider_corbeille()` : Vide la corbeille

#### Mémoire et Contexte
- `noter(note)` : Ajoute une note
- `lire_notes()` : Lit les notes enregistrées
- `memoriser_contexte(categorie, cle, valeur)` : Sauve du contexte durable
- `lire_contexte(categorie)` : Lit une catégorie de contexte
- `memoriser_preference(cle, valeur)` : Sauve une préférence
- `lire_preferences()` : Lit les préférences

#### Organisation
- `analyser_organisation(chemin)` : Produit un plan de rangement
- `organiser_dossier(chemin)` : Range automatiquement un dossier

#### Rappels et Automatisations
- `ajouter_rappel(message, heure)` : Crée un rappel
- `lire_rappels()` : Liste les rappels
- `verifier_rappels()` : Vérifie les rappels dus
- `ajouter_automatisation(nom, outil, args, recurrence, heure)` : Crée une automatisation
- `lister_automatisations()` : Liste les automatisations
- `executer_automatisations_dues()` : Exécute les automatisations arrivées à échéance

#### Surveillance
- `proposer_surveillance_dossiers()` : Propose des dossiers à surveiller
- `ajouter_surveillance_dossier(chemin, recurrence, heure)` : Ajoute une surveillance
- `lister_surveillance_dossiers()` : Liste les surveillances actives
- `executer_surveillance_dossiers(force)` : Exécute les surveillances

#### Commandes Système
- `executer_commande(commande)` : Exécute une commande shell
- `executer_powershell(commande)` : Exécute une commande PowerShell
- `ajouter_commande_personnalisee(nom, commande, description)` : Crée un raccourci
- `executer_commande_personnalisee(nom)` : Exécute un raccourci

## 🏗️ Architecture

Jarvis suit une architecture modulaire stricte :

- **Core Intellect** (`core/intellect.py`) : Le seul composant qui "pense"
- **Tools** (`tools.py`) : Façade stable des outils
- **Capabilities** (`capabilities/`) : Modules d'exécution déterministes
- **Memory** (`core/memory.py`) : Gestion de la mémoire persistante
- **Safety** (`core/safety.py`) : Validation des chemins et confirmations

Pour plus de détails, consultez [ARCHITECTURE.md](ARCHITECTURE.md).

## 🔒 Sécurité

Jarvis utilise une politique de confirmation ciblée :
- Les lectures sont toujours libres
- Les écritures dans l'espace utilisateur sont libres
- Les écritures vers le répertoire Jarvis ou les zones système Windows demandent confirmation
- Le mode Stark désactive les confirmations pour l'autonomie

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) : Documentation technique détaillée
- [EXECUTION_OUTILS.md](EXECUTION_OUTILS.md) : Guide d'exécution des outils

## 🔧 Configuration

### Variables d'Environnement

- `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, ... : Clés API Groq (support multi-clés)
- `OPENROUTER_API_KEY` : Clé API OpenRouter

### Fichiers de Configuration

- `memory.json` : Mémoire persistante (notes, préférences, contexte, automatisations)
- `stark_actif.json` : État des instances Stark actives

## 🚧 Modules Futurs

Les modules suivants sont planifiés mais pas encore implémentés :
- **context_engine** : Perception du contexte permanent
- **datashield** : Protection des données sensibles
- **progress_tracker** : Suivi des progrès sur les tâches
- **syncsphere** : Synchronisation multi-appareils
- **taskflow** : Gestion des flux de tâches complexes

## 🤝 Contribution

Ce projet est développé par Carl-William DJEGUEMA (The Great Corporation). Les contributions sont les bienvenues via les issues et pull requests.

## 📄 Licence

[À définir]

## 🙏 Remerciements

- Inspiration : Jarvis d'Iron Man (Marvel)
- Modèles LLM : Groq, OpenRouter, Ollama
- Bibliothèques : Rich, Psutil, Plyer, FastAPI

---

**Développé avec ❤️ par Carl-William DJEGUEMA - The Great Corporation**
