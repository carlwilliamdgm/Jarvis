# Exécution des Outils - Guide Jarvis

## Vue d'ensemble

Jarvis est maintenant capable d'exécuter les outils à sa disposition de manière **fiable et robuste**. Voici comment ça fonctionne.

## Flux d'exécution

```
1. Utilisateur pose une question/demande
           ↓
2. Détection d'intention (action vs conversation)
           ↓
3. Sélection du bon prompt système
   - Action → Prompt strict JSON
   - Conversation → Prompt libre
           ↓
4. Appel du modèle IA
           ↓
5. Validation de la réponse
   - Si action : vérifie format JSON valide
   - Retry automatique si JSON invalide
           ↓
6. Extraction et exécution des outils
           ↓
7. Retour du résultat à l'utilisateur
```

## Détection d'intention

Jarvis identifie une demande comme "action" si elle contient :

**Mots-clés d'action :**
- Verbes d'action : fais, crée, supprime, liste, organise, exécute, ajouter, lire, audit, etc.
- Contexte : dossier, fichier, mémoire, note, préférence, automatisation, rappel, surveillance
- Synonymes : creer, nettoyer, liberer, optimise, renomme, deplace, copie, etc.

**Patterns supplémentaires :**
- Questions avec "peux-tu", "pourrais-tu", "would you", "can you"
- Phrases avec "s'il te plaît", "please"
- Questions avec structure " fais ", " crée ", etc.

## Format JSON pour les actions

Quand Jarvis doit exécuter une action, il DOIT répondre **UNIQUEMENT** avec du JSON valide :

### Format simple (une action)
```json
{"outil": "noter", "args": {"note": "Tâche importante à faire"}}
```

### Format chaîné (plusieurs actions)
```json
{"outil": "vider_temp", "args": {}}
{"outil": "vider_corbeille", "args": {}}
{"outil": "audit_stockage", "args": {}}
```

### Syntaxe des arguments

```json
{"outil": "creer_fichier", "args": {"chemin": "/home/user/test.txt", "contenu": "Bonjour le monde"}}
{"outil": "ajouter_rappel", "args": {"message": "Appeler maman", "heure": "14:30"}}
{"outil": "executer_commande", "args": {"commande": "dir"}}
```

## Validation et Retry

### Validation stricte
Chaque réponse est validée pour être du JSON :
- ✅ Contient au moins un objet `{}`
- ✅ Chaque objet a une clé `"outil"`
- ✅ Chaque objet a une clé `"args"` de type dictionnaire
- ✅ Les valeurs de `"args"` sont correctes

### Retry automatique
Si la première réponse n'est **pas** du JSON valide et que c'est une action :
1. Jarvis affiche un avertissement
2. Envoie la même demande + instruction de correction au modèle
3. Accepte la nouvelle réponse (max 2 tentatives)

Exemple de retry :
```
User: Fais un audit du stockage
Jarvis: [dim yellow]→ retry modèles cloud (tentative 2)...[/dim yellow]
        [dim]→ Exécution des outils...[/dim]
        → Audit stockage : 245 GB libres...
```

## Outils disponibles (38)

### Gestion des fichiers
- `creer_dossier(chemin)` - Crée un dossier
- `creer_fichier(chemin, contenu)` - Crée un fichier avec contenu
- `lire_fichier(chemin)` - Lit le contenu d'un fichier
- `supprimer(chemin)` - Supprime fichier/dossier (demande confirmation)

### Gestion du stockage
- `audit_stockage()` - Analyse complète du disque
- `top_fichiers_lourds(n=10, complet=False)` - Liste les gros fichiers
- `vider_temp()` - Nettoie les fichiers temporaires
- `vider_corbeille()` - Vide la corbeille

### Mémoire et contexte
- `noter(note)` - Ajoute une note à la mémoire
- `lire_notes()` - Lit toutes les notes
- `memoriser_contexte(categorie, cle, valeur)` - Sauve du contexte durable
- `lire_contexte(categorie)` - Récupère du contexte
- `oublier_contexte(categorie, cle)` - Supprime du contexte
- `memoriser_preference(cle, valeur)` - Sauve une préférence
- `lire_preferences()` - Lit les préférences
- `oublier_preference(cle)` - Supprime une préférence

### Organisation
- `analyser_organisation(chemin)` - Analyse l'ordre d'un dossier
- `organiser_dossier(chemin)` - Range un dossier (demande confirmation)

### Commandes personnalisées
- `ajouter_commande_personnalisee(nom, commande, description)`
- `lister_commandes_personnalisees()`
- `executer_commande_personnalisee(nom)`

### Rappels et automatisations
- `ajouter_rappel(message, heure)` - Ajoute un rappel
- `lire_rappels()` - Liste les rappels
- `supprimer_rappel(rappel_id)` - Supprime un rappel
- `verifier_rappels()` - Vérifie les rappels dus
- `ajouter_automatisation(nom, outil, args, recurrence, heure)` - Crée une tâche automatisée
- `lister_automatisations()` - Liste les automatisations
- `executer_automatisations_dues()` - Exécute les automatisations
- `ajouter_commande_personnalisee(nom, commande, description)` - Commande custom

### Surveillance
- `proposer_surveillance_dossiers()` - Propose des dossiers à surveiller
- `ajouter_surveillance_dossier(chemin, recurrence, heure)` - Ajoute surveillance
- `lister_surveillance_dossiers()` - Liste les surveillances
- `executer_surveillance_dossiers(force=False)` - Exécute les surveillances
- `supprimer_surveillance_dossier(watcher_id)` - Supprime surveillance

### Terminal
- `executer_commande(commande)` - Exécute une commande système

### Proactif
- `bilan_proactif(force=False, niveau="normal")` - Affiche les alertes proactives

## Améliorations apportées

### 1️⃣ Prompt amélioré
- Format JSON clairement délimité avec bordures visuelles
- Exemples concrets et contexte utilisateur
- Instructions strictes "UNIQUEMENT du JSON"

### 2️⃣ Détection d'intention robuste
- 30+ mots-clés reconnus
- Patterns de questions sophistiqués
- Meilleure discrimination action/conversation

### 3️⃣ Validation JSON stricte
- Extraction validée de chaque objet JSON
- Vérification des clés requises ("outil", "args")
- Type checking pour "args" (doit être dict)

### 4️⃣ Système de retry intelligent
- Max 2 tentatives pour obtenir du JSON valide
- Message d'aide lors du retry
- Gestion d'erreur gracieuse

### 5️⃣ Messages d'erreur clairs
- Indication visuelle des tentatives
- Explications détaillées des problèmes
- Suggestions de reformulation

## Exemples d'utilisation

### Exemple 1 : Créer une note
```
User: Crée une note "Réunion à 15h"
Jarvis: {"outil": "noter", "args": {"note": "Réunion à 15h"}}
Result: Note créée et sauvegardée dans la mémoire
```

### Exemple 2 : Audit stockage
```
User: Fais un audit du stockage
Jarvis: {"outil": "audit_stockage", "args": {}}
Result: Analyse complète du disque affichée
```

### Exemple 3 : Chaîner des actions
```
User: Nettoie l'ordinateur
Jarvis: {"outil": "vider_temp", "args": {}}
        {"outil": "vider_corbeille", "args": {}}
        {"outil": "audit_stockage", "args": {}}
Result: Trois outils exécutés en séquence
```

### Exemple 4 : Conversation (pas d'action)
```
User: Que fais-tu normalement?
Jarvis: Je suis Jarvis, votre assistant IA local...
(Pas d'exécution d'outil, réponse libre)
```

## Dépannage

### Jarvis ne lance pas l'outil
1. ✅ Vérifiez que votre demande contient un mot-clé d'action
2. ✅ Reformulez avec un verbe d'action clair (fais, crée, supprime, etc.)
3. ✅ Vérifiez les logs pour voir si du JSON a été généré

### Erreur "arguments invalides"
1. ✅ Vérifiez la syntaxe JSON
2. ✅ Assurez-vous que les clés sont correctes (ex: "chemin" not "path")
3. ✅ Relancez l'outil après reformulation

### Modèle cloud indisponible
1. ✅ Jarvis bascule automatiquement sur le modèle local
2. ✅ Les outils fonctionnent avec n'importe quel modèle
3. ✅ Aucune action manuelle requise

## Architecture sous-jacente

```
jarvis.py
├── detecter_intention() → détermine action/conversation
├── parler() → appelle le modèle + retry si needed
├── valider_reponse_json() → valide format JSON
├── extraire_json_objets() → parse les objets JSON
├── executer_outil() → exécute les outils extraits
└── main() → boucle REPL principale

core/prompt.py
├── construire_prompt_action() → instructions strictes JSON
└── construire_prompt_conversation() → libre

tools.py
└── OUTILS → dict de toutes les fonctions disponibles
```

## Conclusion

Jarvis est maintenant **pleinement capable** d'exécuter ses outils de manière fiable. Le système :
- ✅ Détecte les intentions d'action
- ✅ Force le format JSON via le prompt
- ✅ Valide la réponse strictement
- ✅ Réessaye automatiquement si needed
- ✅ Exécute les outils avec gestion d'erreur complète
- ✅ Retourne des résultats clairs à l'utilisateur

**Commencez simplement :** Lancez `jarvis.py` et demandez à Jarvis de faire quelque chose !
