# Execution des outils - Guide Jarvis

Ce document decrit l'etat actuel de l'execution des outils dans Jarvis. L'ancien modele "detection action/conversation puis prompt JSON separe" a ete remplace par un flux centre sur Core Intellect.

## Vue d'ensemble

Jarvis utilise un registre unique d'outils dans `tools.py`. Le LLM ne les execute jamais directement : il renvoie une intention structuree, puis `jarvis.py` appelle les fonctions Python correspondantes.

Le contrat actuel de Core Intellect est :

```json
{
  "objectif": "description courte",
  "type": "action|conversation|diagnostic|planification|mixte",
  "actions": [
    {"outil": "nom_outil", "args": {"cle": "valeur"}}
  ],
  "reponse": "reponse naturelle pour l'utilisateur"
}
```

## Flux d'execution normal

```text
1. Message utilisateur
        |
2. jarvis.py intercepte les commandes locales (!a, !S, mode action)
        |
3. core.intellect.interpreter_objectif()
        |
4. Appel modele cloud disponible, sinon modele local
        |
5. Parsing JSON de decision et filtrage des outils inconnus
        |
6. jarvis.py execute les actions via tools.OUTILS
        |
7. Reponse naturelle + resultats d'outils
        |
8. Journalisation dans memory.json
```

## Modes d'execution

### Mode normal

Chaque message est envoye a Core Intellect. Si le resultat contient des actions, elles sont executees dans l'ordre. Sinon, Jarvis repond en conversation.

### Mode action one-shot

`!a` ou "mode action" force le prochain message a etre traite comme une commande directe. Le flag est remis a zero juste apres.

### Mode Stark

`!S <objectif>` lance une boucle autonome structuree.

- `>>` separe les macro-etapes.
- `&&` impose une dependance gauche-droite.
- `||` definit des alternatives/replis.
- Chaque micro-objectif a 3 tentatives maximum.
- Le LLM ne recoit que le micro-objectif courant et le resume compact des tentatives precedentes de ce meme micro-objectif.
- Deux tentatives identiques consecutives arretent le micro-objectif pour pietinement.
- Les confirmations interactives sont court-circuitees pendant Stark pour eviter un blocage.
- `terminer_tache(resume)` sert a signaler qu'un micro-objectif est atteint.

## Modeles et retry

Core Intellect essaie les providers disponibles dans cet ordre logique :

- Groq si une ou plusieurs cles `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, etc. sont configurees.
- OpenRouter si `OPENROUTER_API_KEY` est configuree.
- Ollama local avec `qwen2.5:7b` en fallback.

Les appels LLM ont deux tentatives. Les outils fonctionnent avec n'importe quel provider tant que la reponse finale respecte le contrat JSON attendu.

## Parsing et validation

`core.intellect` extrait un unique objet JSON de decision. Si le JSON est invalide ou incomplet, Jarvis retombe sur une reponse conversationnelle d'erreur. Les actions sont ensuite filtrees :

- chaque action doit etre un dictionnaire;
- `outil` doit exister dans `tools.OUTILS`;
- les outils inconnus sont retires avant execution;
- les erreurs d'arguments sont capturees au moment de l'appel Python.

`jarvis.py` conserve aussi des helpers d'extraction d'objets JSON pour compatibilite avec certains flux et tests.

## Confirmations et securite

La politique actuelle est basee sur la confirmation ciblee.

- Lecture : libre.
- Ecriture dans l'espace utilisateur : libre.
- Ecriture dans `JARVIS_DIR` ou une zone systeme Windows : confirmation.
- Mode Stark : aucune confirmation interactive.
- Les chemins sont normalises par `chemin_autorise()`.
- Les automatisations refusent les outils declares non automatisables dans `capabilities.scheduler.OUTILS_AUTOMATISATION_INTERDITS`.

`action_bloquee()` et certains alias historiques existent encore pour compatibilite, mais la logique actuelle ne bloque pas par zone : elle demande confirmation quand c'est necessaire.

## Outils disponibles (43)

### Fichiers

- `creer_dossier(chemin)` - Cree un dossier.
- `creer_fichier(chemin, contenu="")` - Cree un fichier avec contenu optionnel.
- `lire_fichier(chemin, max_caracteres=200000)` - Lit un fichier avec limite anti-blocage.
- `lister_dossier(chemin, limite=200)` - Liste un dossier avec limite d'affichage.
- `supprimer(chemin)` - Supprime fichier ou dossier apres confirmation si requise.

### Stockage et notifications

- `audit_stockage()` - Analyse le stockage.
- `top_fichiers_lourds(n=10, complet=False, max_secondes=15)` - Liste les plus gros fichiers avec limite de temps.
- `vider_temp()` - Nettoie les fichiers temporaires.
- `vider_corbeille()` - Vide la corbeille.
- `notifier_utilisateur(titre, message, urgence=False)` - Envoie une notification systeme.
- `bilan_proactif(force=False, niveau="normal")` - Regroupe les signaux proactifs utiles.

### Memoire et contexte

- `noter(note)` - Ajoute une note.
- `lire_notes()` - Lit les notes.
- `memoriser_contexte(categorie, cle, valeur)` - Sauve du contexte durable.
- `lire_contexte(categorie=None)` - Lit une categorie ou tout le contexte.
- `oublier_contexte(categorie, cle)` - Supprime une entree de contexte.
- `memoriser_preference(cle, valeur)` - Sauve une preference.
- `lire_preferences()` - Lit les preferences.
- `oublier_preference(cle)` - Supprime une preference.
- `enregistrer_echange(utilisateur, jarvis)` - Journalise un echange.

### Organisation

- `analyser_organisation(chemin)` - Produit un plan de rangement.
- `organiser_dossier(chemin)` - Range les fichiers par categorie apres confirmation si requise.

### Rappels et automatisations

- `ajouter_rappel(message, heure)` - Ajoute un rappel.
- `lire_rappels()` - Liste les rappels.
- `supprimer_rappel(rappel_id)` - Supprime un rappel.
- `verifier_rappels()` - Verifie les rappels dus.
- `ajouter_automatisation(nom, outil, args=None, recurrence="quotidien", heure="09:00")` - Cree une automatisation si l'outil est autorise.
- `lister_automatisations()` - Liste les automatisations.
- `executer_automatisation(automation_id=None, nom=None)` - Lance une automatisation active.
- `executer_automatisations_dues()` - Execute les automatisations arrivees a echeance.

### Surveillance de dossiers

- `proposer_surveillance_dossiers()` - Propose des dossiers a surveiller.
- `ajouter_surveillance_dossier(chemin, recurrence="quotidien", heure="09:00")` - Ajoute une surveillance.
- `lister_surveillance_dossiers()` - Liste les surveillances.
- `executer_surveillance_dossiers(force=False)` - Execute les surveillances dues ou forcees.
- `supprimer_surveillance_dossier(watcher_id)` - Supprime une surveillance.

### Commandes

- `executer_commande(commande)` - Execute une commande systeme.
- `executer_powershell(commande)` - Execute une commande PowerShell native.
- `ajouter_commande_personnalisee(nom, commande, description="")` - Enregistre une commande custom.
- `lister_commandes_personnalisees()` - Liste les commandes custom.
- `executer_commande_personnalisee(nom)` - Execute une commande custom.

### Traducteur

- `lire_traducteur()` - Affiche les entrees et statistiques du traducteur.
- `modifier_traducteur(cle, patterns_fr, patterns_en, outil="", args_json="{}")` - Flux de demande de modification du traducteur. Actuellement, la persistance reelle n'est pas implementee.

### Controle agentique

- `terminer_tache(resume="Tache terminee.")` - Signale la fin d'un objectif ou micro-objectif.

## Exemples

### Note simple

Demande :

```text
Note que la reunion produit est a 15h.
```

Action attendue :

```json
{"outil": "noter", "args": {"note": "La reunion produit est a 15h."}}
```

### Lecture de dossier

Demande :

```text
Liste le contenu du dossier Downloads.
```

Action attendue :

```json
{"outil": "lister_dossier", "args": {"chemin": "Downloads"}}
```

### Stark sequence

Demande :

```text
!S audite le stockage >> liste les gros fichiers && (notifie le resultat || note le resultat)
```

Effet :

- `audite le stockage` doit reussir avant la suite.
- `liste les gros fichiers` doit reussir avant la branche de notification.
- `notifie le resultat` est tente avant `note le resultat`.

## Depannage

### Aucun outil ne se lance

- Verifier que Core Intellect a renvoye une action dans `actions`.
- Reformuler avec un verbe concret.
- Verifier que le nom d'outil existe dans `tools.OUTILS`.

### Erreur d'arguments

- Comparer les noms d'arguments avec les signatures ci-dessus.
- Les erreurs `TypeError` sont capturees par `jarvis.py` et retournees dans le resultat.

### Confirmation inattendue

- Les confirmations apparaissent pour `JARVIS_DIR` et les zones systeme.
- En mode Stark, elles doivent etre ignorees automatiquement.
- Si un outil appelle `_console.input()` directement, il doit etre adapte pour passer par `demander_confirmation()`.

### Provider LLM indisponible

- Jarvis essaie les providers cloud configures.
- En cas d'echec, il essaie Ollama local.
- Si tous les providers echouent, Core Intellect retourne une reponse d'erreur sans executer d'action.

## Architecture resumee

```text
jarvis.py
├── detecter_commande_mode()
├── parler()
├── executer_mode_stark()
├── executer_agent()
└── AutonomousAgent

core/intellect.py
├── interpreter_objectif()
├── _parser_reponse_intellect()
└── _appeler_llm_avec_retry()

tools.py
└── OUTILS

capabilities/
└── execution concrete des outils
```

## Principes a conserver

- Ne pas ajouter d'outil sans l'ajouter au prompt de Core Intellect et a ce document.
- Ne pas laisser une capability appeler le LLM.
- Ne pas contourner `tools.py` pour une action exposee a Jarvis.
- Ne pas introduire de confirmation interactive dans Stark.
- Garder les outils automatisables separes des outils sensibles ou bloquants.
