# Execution des outils - Guide Jarvis

Ce document decrit l'etat actuel de l'execution des outils dans Jarvis. L'ancien modele "detection action/conversation puis prompt JSON separe" a ete remplace par un flux centre sur Core Intellect.

## Vue d'ensemble

Jarvis et GreatOS utilisent un registre typé d'outils dans `taskflow/tools.py` (`LegacyToolRegistry(dict)`). Le LLM ne les exécute jamais directement : il renvoie une intention ou un plan ordonné (`ExecutionPlan` / `PlanStep`), puis Jarvis délègue l'exécution au dispatcher central `execute_capability()`, validé au préalable par DataShield (`evaluate_capability`).

L'inventaire des capacités est généré en temps réel depuis `OUTILS` par `core_intellect/tool_signatures.py`. Les prompts et l'outil `lire_capacites()` utilisent donc l'état courant du registre, pas une liste de documentation recopiée à la main.

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
1. Message utilisateur (console, API, Tkinter ou web)
        |
2. executer_interaction_utilisateur() prépare le message et journalise l'échange
        |
3. jarvis/agent.py intercepte les commandes (!a, !S, mode action)
        |
4. core_intellect.intellect.interpreter_objectif() ou planifier_objectif()
        |
5. Résolution de plan / actions ordonnées (ExecutionPlan / PlanStep)
        |
6. Évaluation préalable DataShield (evaluate_capability -> allow | confirm | deny)
        |
7. Dispatcher central execute_capability() invoque le module propriétaire souverain
        |
8. CapabilityResult structuré retourné (statut, durée, résultat, erreur éventuelle)
        |
9. Traçabilité Context Engine (journaliser_resultat_capacite avec assainissement des secrets)
        |
10. Mesure Progress Tracker (enregistrer_impact_capacite et liaison aux objectifs)
        |
11. Restitution de la réponse naturelle et émission des événements
```

En streaming SSE (`GET /jarvis/stream?message=...`), les interfaces recoivent aussi les evenements intermediaires emis pendant ce flux : reflexion, provider, cycle de vie des outils, demandes de confirmation, activation Stark, actions Stark, rapport Stark, reponse finale et erreurs.

## Transport API et interfaces

Le transport HTTP vit dans `interface_morphique/server.py`.

### Endpoint final

`POST /jarvis/ask` garde la compatibilite avec les clients simples. Comme `GET /jarvis/stream`, il appelle `executer_interaction_utilisateur()` puis retourne :

```json
{
  "response": "...",
  "is_action": false,
  "actions_executed": []
}
```

### Endpoint streaming

`GET /jarvis/stream?message=...` est le chemin recommande pour les interfaces modernes. Il retourne `text/event-stream`.

Evenements emis :

- `thinking` : Jarvis commence a reflechir.
- `provider` : un provider LLM repond.
- `tool_started` : une action normale ou Stark commence.
- `tool_completed` : une action se termine.
- `tool_failed` : une action echoue ou est refusee.
- `confirmation_required` : une action attend la decision de l'interface; elle contient `action_id`, `description` et `expires_at`.
- `stark_activated` : le Mode Stark s'active.
- `stark_action` : une action Stark est executee.
- `stark_terminated` : le Mode Stark termine ou s'interrompt.
- `response` : reponse finale.
- `error` : erreur.
- `done` : fin de stream.

### Endpoints de planification ordonnée

- `POST /jarvis/plan` : accepte un objectif (`{"goal": "..."}`) et retourne un plan ordonné `ExecutionPlan` (`PlanStep`) conçu par Core Intellect sans l'exécuter.
- `GET /jarvis/plan/stream?goal=...` : orchestre le plan étape par étape en streaming SSE avec évaluation de sécurité DataShield, émettant les événements :
  - `plan_created` : plan conçu avec liste des étapes ordonnées, dépendances et préconditions.
  - `step_started` : démarrage d'une étape spécifique.
  - `policy_decision` : résultat du contrôle DataShield (`allow`, `confirm`, `deny`).
  - `step_completed` : étape achevée avec son `CapabilityResult`.
  - `plan_completed` : exécution du plan terminée avec rapport global.


Les interfaces ne doivent pas reconstituer l'etat en appelant `/jarvis/ask` en parallele. Elles consomment le flux SSE et affichent chaque evenement dans l'ordre.

### Clients

- `interface_morphique/app.py` consomme le SSE avec `requests.get(..., stream=True)` dans un thread separe.
- `interface_morphique/web/index.html` consomme le SSE avec `EventSource`.
- Le terminal Rich continue d'utiliser les appels `console.print()` existants ; les evenements SSE sont emis en parallele.

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
- Chaque micro-objectif a 5 decisions maximum (`MAX_ETAPES_PAR_MICRO_OBJECTIF = 5`).
- Le LLM ne recoit que le micro-objectif courant et le resume compact des tentatives precedentes de ce meme micro-objectif.
- Deux tentatives identiques consecutives arretent le micro-objectif pour pietinement.
- Les confirmations interactives sont court-circuitees pendant Stark pour eviter un blocage.
- `terminer_tache(resume)` sert a signaler qu'un micro-objectif est atteint.

## Modeles et retry

Core Intellect utilise une cascade intelligente de providers LLM :

1. **Cloud Ultra-Rapide (Priorité #1)** : Groq / OpenRouter
   - Temps de réponse < 1s
   - Modèles puissants (120B/70B paramètres)
   - Mémorisation du dernier provider fonctionnel pour optimisation

2. **Modèle Souverain Jarvis-GC (Fallback Hors-Ligne #1)** : The Great Corporation
   - Base Qwen 2.5 (1.5B/3B/7B) optimisé CPU/AVX2
   - Prompt système gravé dans le Modelfile
   - Timeout stricte configurable (45s par défaut)
   - Premier choix hors-ligne

3. **Fallback Local Standard** : Ollama qwen2.5:7b
   - Dernier recours si cloud et Jarvis-GC indisponibles

### Configuration des providers

- Groq : `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, etc.
- OpenRouter : `OPENROUTER_API_KEY`
- Jarvis-GC : Modèle local via Ollama (`ollama create jarvis-gc -f models/jarvis_gc/Modelfile`)
- Variables avancées Jarvis-GC :
  - `JARVIS_GC_TIMEOUT` : Timeout en secondes (défaut: 45)
  - `JARVIS_GC_THREADS` : Nombre de threads (défaut: 4)
  - `JARVIS_MODEL_HOST` : Host Ollama personnalisé

Les appels LLM ont deux tentatives. Les outils fonctionnent avec n'importe quel provider tant que la reponse finale respecte le contrat JSON attendu.

## Parsing et validation

`core_intellect.intellect` extrait un unique objet JSON de decision. Si le JSON est invalide ou incomplet, Jarvis retombe sur une reponse conversationnelle d'erreur. Les actions sont ensuite filtrees :

- chaque action doit être un dictionnaire ;
- `outil` doit exister dans le registre `OUTILS` (`LegacyToolRegistry`) ou correspondre à une capacité canonique résolue par `greatos_capabilities.py` ;
- les outils inconnus sont retirés avant exécution ;
- les arguments sont validés lors de la construction de `CapabilityRequest`.

Une décision de type `action` ou `mixte` sans outil exécutable déclenche une passe de réparation à température zéro. Si elle ne produit toujours aucun outil valide, Jarvis indique explicitement qu'aucune action n'a été exécutée ; il ne présente pas une action comme accomplie.

`jarvis/agent.py` conserve aussi des helpers d'extraction d'objets JSON pour compatibilité avec certains flux et tests.

## Confirmations et politique DataShield

La politique de sécurité est désormais centralisée dans `datashield/policy.py` (`evaluate_capability()`) avec gouvernance DEFCON :

- **DEFCON 1** : Urgence absolue, blocage systématique de toutes les capacités.
- **DEFCON 2** : Blocage total des opérations destructives (`filesystem.delete`, suppression de corbeille) et confirmation requise pour toute écriture.
- **DEFCON 3** : Confirmation obligatoire pour les commandes système et opérations critiques.
- **DEFCON 4 / 5 (Nominal)** : Écritures utilisateur libres ; confirmation ciblée sur les zones protégées (`JARVIS_DIR`, Windows, Program Files).
- **Mode Stark** : autonome, mais strictement confiné aux droits du compte courant et soumis à l'évaluation DataShield.
- Les chemins sont normalisés par `chemin_autorise()`.
- Les automatisations refusent les outils declares non automatisables dans `taskflow.scheduler.OUTILS_AUTOMATISATION_INTERDITS`.

`action_bloquee()` et certains alias historiques existent encore pour compatibilite, mais la logique actuelle ne bloque pas par zone : elle demande confirmation quand c'est necessaire.

### Bilan de session — modèle de permissions discuté (2026-10-01)

Cette section distingue les constats du code actuel des décisions de conception exprimées pendant la session. Elle ne signifie pas que les changements décrits dans la politique cible ont déjà été implémentés.

#### Objectif fixé

GreatOS/Jarvis doit rester une surcouche de l'OS hôte et se comporter comme un utilisateur standard de GreatOS. Le compte OS sous lequel Jarvis s'exécute fournit le plafond réel de ses droits : la trust matrix, le mode action et le mode Stark peuvent éviter les confirmations Jarvis selon leurs règles, mais ne donnent jamais à Jarvis des privilèges que ce compte ne possède pas. Toute élévation nécessaire appartient à Windows/UAC (ou au mécanisme équivalent de l'OS hôte).

Seuls deux espaces sont considérés comme protégés par la politique cible : l'espace de l'OS hôte et celui de la surcouche GreatOS. Les autres actions restent limitées par les permissions effectives du compte OS. Le but est d'éviter les confirmations inutiles pour le travail quotidien tout en gardant les limites de l'OS.

La distinction propriétaire/tiers a également été clarifiée au niveau conceptuel : le propriétaire est l'utilisateur du compte OS qui exécute GreatOS à l'instant T ; les tiers peuvent être mémorisés comme personnes, sans recevoir les privilèges du propriétaire. L'identification comportementale des personnes est hors objectif immédiat. L'authentification/API multi-utilisateur reste un chantier séparé si une identité distincte du compte OS devient nécessaire.

#### Ce qui a été vérifié ou fait

- L'audit du code a confirmé que `datashield/policy.py` produit les décisions `ALLOW`, `CONFIRM` ou `DENY`, tandis que la trust matrix est une couche distincte qui décide si une confirmation de confiance est demandée.
- La matrice actuelle suit les capacités par domaine et promeut après 5 succès consécutifs. Les niveaux 0 et 1 demandent une confirmation ; le niveau 2 permet une action avec notification et le niveau 3 une action silencieuse.
- Le code actuel cartographie notamment `JARVIS_DIR`, `SystemRoot`, `Program Files`, `ProgramData` et `Common Files` comme racines protégées. Pour les opérations concernées, cette protection provoque principalement une confirmation, pas un refus absolu ; `chemin_autorise()` normalise le chemin mais n'est pas une barrière d'accès au système de fichiers.
- L'évaluation centrale applique DEFCON 1 (blocage général), DEFCON 2 (blocage système/destructif et confirmation des écritures) et DEFCON 3 (confirmation des commandes système). DEFCON 4 n'a pas de règle distincte dans cette fonction.
- La session a identifié que les points d'appel inspectés ne renseignent pas explicitement `RequestOrigin.EXTERNAL` : la protection de provenance prévue pour les contenus externes doit être vérifiée avant d'être considérée comme active.
- Aucun changement du comportement produit n'a été effectué pendant cette discussion. La proposition d'augmenter le seuil de promotion à 10 succès par palier était une piste, pas une décision adoptée.

#### Écarts et suite à faire

1. Définir précisément les frontières des deux espaces protégés (« OS hôte » et « surcouche GreatOS »), notamment pour les autres OS, et vérifier que la cartographie actuelle correspond à cette définition sans protéger involontairement tout un espace utilisateur.
2. Traduire la politique cible en règles exécutables : opérations courantes autorisées sans friction dans le périmètre du compte OS ; confirmations de confiance pilotées par la matrice ; limites des espaces protégés maintenues ; aucune élévation de privilèges accordée par GreatOS.
3. Vérifier séparément l'effet du mode action, du mode Stark et des niveaux de confiance sur chaque chemin d'exécution, en veillant à ce qu'ils ne court-circuitent pas les refus absolus de sécurité.
4. Décider si les actions vers les espaces protégés sont confirmées ou refusées par GreatOS, et comment les demandes d'élévation OS sont déclenchées. Une commande lancée sans demande d'élévation explicite peut être refusée par l'OS sans afficher UAC.
5. Propager et tester la provenance des demandes externes avant de s'appuyer sur la règle anti-injection correspondante.
6. Après implémentation, exécuter un essai quotidien contrôlé : lecture et écriture ordinaires, action vers chaque espace protégé, commande nécessitant une élévation, refus d'une action bloquée, puis répétition après progression de confiance.

Le seuil de promotion de la trust matrix reste à arbitrer : la valeur actuelle est 5 ; la valeur 10 a été proposée pendant la discussion mais n'a pas été validée par l'utilisateur.

## Outils disponibles

La liste reelle est dynamique. Utiliser `lire_capacites()` ou `core_intellect.tool_signatures.documenter_signatures_outils()` pour obtenir l'inventaire exact du registre courant.

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
- `lire_journal_agents(limite=10)` - Consulte les relais structurés laissés par les agents de développement dans le journal d'apprentissage GreatOS.
- `lire_traces_capacites(limite=10)` - Consulte les traces d'exécution des capacités GreatOS enregistrées dans Context Engine.

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

### Controle bureau et environnement

- `controler_multimedia(action)` - Pilote le flux multimedia universel (pause, play, toggle, suivant, precedent, volume_up, volume_down, mute).
- `manipuler_fenetre(titre, x=0, y=0, largeur=1280, hauteur=720)` - Repositionne ou redimensionne une fenetre visible sur le bureau de Carl.
- `regarder_ecran(question="", zone="ecran")` - Capture l'ecran ou la fenetre active en direct et l'analyse visuellement via le modele multimodal VLM.

### Traducteur



- `lire_traducteur()` - Affiche les entrees et statistiques du traducteur.
- `modifier_traducteur(cle, patterns_fr, patterns_en, outil="", args_json="{}")` - Flux de demande de modification du traducteur. Actuellement, la persistance reelle n'est pas implementee.

### Capacites

- `lire_capacites()` - Retourne l'inventaire actuel des outils publics de Jarvis depuis `tools.OUTILS`.

### Controle agentique

- `terminer_tache(resume="Tache terminee.")` - Signale la fin d'un objectif ou micro-objectif.

### Calendrier et emails

- `evenements_aujourdhui()` - Obtient les événements calendrier pour aujourd'hui.
- `rappels_calendrier()` - Vérifie les rappels de calendrier imminents.
- `resume_emails()` - Obtient un résumé de la situation email.
- `emails_urgents()` - Détecte et affiche les emails urgents.

### Intelligence comportementale

- `suggerer_actions()` - Génère et affiche des suggestions contextuelles intelligentes.
- `analyser_patterns()` - Analyse et affiche les patterns comportementaux détectés.
- `detecter_automatisations()` - Détecte et suggère des automatisations potentielles.
- `rapport_performance()` - Génère un rapport de performance de Jarvis.
- `insights_apprentissage()` - Obtient des insights basés sur les apprentissages enregistrés.
- `generer_rapport_conscience()` - Génère un rapport complet de conscience Jarvis.

### Recherche sémantique

- `analyser_insights()` - Analyse et affiche les insights profonds basés sur la recherche sémantique.
- `enrichir_memoire()` - Enrichit la mémoire avec des métadonnées temporelles et contextuelles.
- `rechercher(requete)` - Effectue une recherche sémantique dans les interactions passées.

### Monitoring système

- `rapport_systeme()` - Génère un rapport complet de l'état système.
- `tendances_systeme(heures=24)` - Analyse les tendances système sur une période donnée.

### Réseau & Tailscale

- `decouvrir_appareils_tailscale()` - Détecte l'IP locale et la liste des appareils pairs connectés sur le Tailnet privé.

### Recherche Web

- `rechercher_web(requete, max_resultats=5)` - Effectue une recherche web via DuckDuckGo ou moteur configuré.
- `analyser_page_web(url)` - Extrait et analyse le contenu textuel d'une page web.
- `rechercher_et_analyser(requete, max_resultats=3)` - Recherche et analyse les pages pertinentes.
- `extraire_informations_cles(url, sujet)` - Extrait des informations ciblées sur un sujet précis depuis une URL.
- `synthetiser_resultats(resultats, requete)` - Synthétise un ensemble de résultats web.

### Automatisation de Navigateur

- `accomplir_tache_web(objectif, url_depart="", headless=True)` - **Agent de navigation autonome** : accomplit une tâche web complexe en pilotant le navigateur (navigue, clique, remplit des formulaires, extrait du contenu) à la façon de Claude dans Chrome. Exemple : *"Cherche le prix du vol Paris-Montréal le 15 oct sur Google Flights"*.
- `naviguer_vers(url)` - Navigue vers une URL dans le navigateur contrôlé.
- `cliquer_element(selecteur)` - Clique sur un élément via sélecteur CSS ou texte.
- `remplir_formulaire(selecteur, texte)` - Saisit du texte dans un champ de formulaire.
- `extraire_texte_page(selecteur="")` - Extrait le texte complet ou d'une zone de la page.
- `prendre_capture(nom_fichier="capture.png")` - Capture l'écran de la page active.
- `executer_sequence(actions)` - Exécute une séquence d'actions de navigation.
- `obtenir_infos_page()` - Récupère le titre et l'URL de la page courante.
- `fermer_navigateur()` - Ferme la session de navigation persistante et libère les ressources Chromium.
- `reinitialiser_navigateur()` - Réinitialise la session de navigation persistante (ferme et rouvre).


### Sessions de Navigation & Overlay

- `demarrer_overlay_navigation()` - Démarre le visualiseur d'overlay du navigateur avec interface visuelle temps réel.
- `arreter_overlay_navigation()` - Arrête l'overlay de navigation.
- `creer_session_navigation(url="", browser_type="chromium", headless=False)` - Crée une nouvelle session de navigation persistante avec états et événements.
- `naviguer_session(session_id, url)` - Charge une page dans une session spécifique (non-bloquant).
- `cliquer_session(session_id, selecteur)` - Clique sur un élément dans une session spécifique (non-bloquant).
- `remplir_session(session_id, selecteur, texte)` - Saisit du texte dans une session spécifique (non-bloquant).
- `capture_session(session_id, chemin="")` - Capture la vue d'une session de navigation (non-bloquant).
- `executer_js_session(session_id, script)` - Exécute un script JavaScript dans la session (non-bloquant).
- `fermer_session(session_id)` - Ferme et nettoie une session de navigation.
- `lister_sessions()` - Liste toutes les sessions de navigation actives avec état détaillé.
- `obtenir_etat_session(session_id)` - Obtient l'état complet, l'historique et les métadonnées d'une session.

## Modules internes

Les fonctions suivantes ne sont pas exposées comme outils Jarvis mais sont utilisées en interne par le système :

### Interface vocale (jarvis/voice_overlay.py, jarvis/voice_input.py, jarvis/voice_output.py)
- `activer_vocal()` - Active l'interface vocale (reconnaissance et synthèse)
- `desactiver_vocal()` - Désactive l'interface vocale
- `lire_etat_vocal()` - Retourne l'état vocal actuel (IDLE, LISTENING, THINKING, SPEAKING, ERROR)
- `configurer_vocal(parametres)` - Configure les paramètres vocaux (langue, vitesse, volume, modèles)

### Monitoring système (core/system_monitor.py)
- `obtenir_etat_systeme()` - Retourne un état complet du système (CPU, mémoire, disque, réseau, processus)
- `detecter_anomalies()` - Détecte les anomalies dans l'état système (CPU, mémoire, disque)

### Intelligence comportementale (core/contextual_suggestions.py, core/decision_analyzer.py)
- `generer_suggestions_contextuelles()` - Génère des suggestions intelligentes basées sur patterns, état système et contexte
- `analyser_decisions_recentes(jours=7)` - Analyse les décisions récentes pour identifier patterns de succès/échec
- `detecter_patterns_erreur()` - Détecte les patterns d'erreur récurrents avec suggestions de correction
- `memoriser_succes(outil, args, contexte)` - Mémorise une solution réussie pour réutilisation future
- `rechercher_solution_similaire(outil, contexte)` - Recherche une solution similaire dans l'historique des succès

### Recherche sémantique (core/semantic_search.py)
- `rechercher_semantique(requete, limite=10)` - Effectue une recherche sémantique dans les interactions
- `analyser_connexions_contextuelles()` - Analyse les connexions entre différents contextes
- `generer_insights_profonds()` - Génère des insights profonds basés sur l'analyse contextuelle

### Personnalité (core/personality.py)
- `obtenir_personnalite()` - Retourne la personnalité actuelle de Jarvis avec tous les traits
- `ajuster_personnalite(trait, delta)` - Ajuste un trait de personnalité avec une variation entre -1 et 1
- `adapter_ton_contextuel(message)` - Adapte le ton de réponse en fonction du contexte et de l'humeur détectée
- `generer_prompt_personnalite()` - Génère un prompt de personnalité pour le LLM
- `evoluer_personnalite()` - Fait évoluer la personnalité basée sur les interactions passées
- `obtenir_rapport_personnalite()` - Génère un rapport de personnalité avec traits et évolution
- `reinitialiser_personnalite()` - Réinitialise la personnalité aux valeurs de base

### Navigation et Sessions (core/browser_session.py, core/browser_overlay.py)
- `get_session_manager()` - Retourne le gestionnaire global de sessions de navigateur
- `create_session(session_id, headless=True)` - Crée une nouvelle session de navigation persistante
- `get_session(session_id)` - Retourne une session spécifique par son ID
- `list_sessions()` - Liste toutes les sessions actives avec leur état
- `start_browser_overlay()` - Démarre l'overlay visuel de navigation
- `stop_browser_overlay()` - Arrête l'overlay visuel de navigation
- `BrowserSession.start()` - Démarre une session dans un thread dédié
- `BrowserSession.stop()` - Arrête une session proprement
- `BrowserSession.navigate_sync(url)` - Navigation synchrone bloquante
- `BrowserSession.navigate(url)` - Navigation asynchrone non-bloquante
- `BrowserSession.click_sync(selector)` - Clic synchrone bloquant
- `BrowserSession.click(selector)` - Clic asynchrone non-bloquant
- `BrowserSession.fill_sync(selector, value)` - Remplissage synchrone bloquant
- `BrowserSession.fill(selector, value)` - Remplissage asynchrone non-bloquant
- `BrowserSession.screenshot_sync(path)` - Capture synchrone bloquante
- `BrowserSession.screenshot(path)` - Capture asynchrone non-bloquante

### Client LLM (core_intellect/llm_client.py)
- `get_llm_client()` - Retourne l'instance globale du client LLM
- `modele_souverain_disponible()` - Vérifie si le modèle Jarvis-GC est disponible
- `chat_with_jarvis_gc(modele, messages, temperature)` - Appel direct au modèle souverain
- `get_groq_clients()` - Retourne les clients Groq configurés
- `chat_with_cloud(modele, messages, temperature)` - Appel au provider cloud (Groq)
- `chat_with_openrouter(modele, messages, temperature)` - Appel au provider OpenRouter
- `chat_with_local(modele, messages, temperature)` - Appel au provider local Ollama
- `providers_cloud_disponibles()` - Liste les providers cloud disponibles
- `ordonner_providers_cloud(providers, memoire, complexite)` - Ordonne les providers par priorité
- `memoriser_provider_cloud(nom_provider)` - Mémorise le dernier provider fonctionnel

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

core_intellect/intellect.py
├── interpreter_objectif()
├── _parser_reponse_intellect()
└── _appeler_llm_avec_retry()

core_intellect/llm_client.py
├── LLMClient (orchestrateur cascade)
├── JarvisGCProvider (modèle souverain)
├── GroqProvider (cloud ultra-rapide)
├── OpenRouterProvider (cloud alternatif)
├── OllamaProvider (fallback local)
└── generate_with_fallback()

jarvis/voice_state.py
├── get_voice_state()
├── _set_voice_state()
└── _write_state_to_file()

jarvis/voice_overlay.py
├── VoiceOverlay class
├── _read_state_from_file()
├── _update_visuals()
└── _check_state_loop()

core/browser_session.py
├── BrowserSession (session persistante)
├── BrowserSessionState (états enum)
├── SessionManager (gestionnaire global)
├── Méthodes synchrones (navigate_sync, click_sync, etc.)
└── Méthodes asynchrones (navigate, click, etc.)

core/browser_overlay.py
├── BrowserOverlay class
├── _update_display()
├── _get_state_color()
└── _get_state_icon()

core/contextual_suggestions.py
├── generer_suggestions_contextuelles()
├── _suggestions_patterns()
├── _suggestions_systeme()
└── _suggestions_temporelles()

core/decision_analyzer.py
├── analyser_decisions_recentes()
├── detecter_patterns_erreur()
├── memoriser_succes()
└── generer_rapport_performance()

core/pattern_analyzer.py
├── analyser_patterns_comportementaux()
├── detecter_automatisations_potentielles()
└── obtenir_patterns_actuels()

core/semantic_search.py
├── indexer_interactions_pour_recherche()
├── rechercher_semantique()
├── analyser_connexions_contextuelles()
└── generer_insights_profonds()

core/system_monitor.py
├── obtenir_etat_systeme_complet()
├── detecter_anomalies()
├── generer_rapport_systeme()
└── obtenir_tendances_systeme()

core/personality.py
├── obtenir_personnalite_actuelle()
├── ajuster_personnalite()
├── adapter_ton_contextuel()
└── evoluer_personnalite()

tools.py
└── OUTILS

taskflow/
├── voice_input.py
├── voice_output.py
├── clap_input.py
├── web_search.py
├── browser_automation.py
├── browser_sessions.py
└── execution concrete des outils
### Outils GreatOS (DataShield, Progress Tracker, SyncSphere)

- `obtenir_niveau_defcon()` : Consulte le niveau de sécurité DEFCON actuel du système.
- `changer_niveau_defcon(niveau)` : Ajuste le niveau DEFCON de 1 (confinement) à 5 (nominal).
- `statut_chiffrement()` : Affiche l'état d'activation et l'algorithme du moteur de chiffrement AES-256-GCM DataShield.
- `chiffrer_valeur(valeur)` : Chiffre une chaîne de caractères avec AES-256-GCM via DataShield.
- `dechiffrer_valeur(blob)` : Déchiffre un blob protégé par DataShield.
- `creer_objectif(id_obj, titre, description, cible, unite)` : Enregistre un nouvel objectif dans le Progress Tracker.
- `lister_objectifs()` : Affiche les objectifs actifs, terminés ou en pause avec leur progression.
- `mettre_a_jour_objectif(id_obj, nouvelle_valeur)` : Met à jour la valeur et le pourcentage de complétion d'un objectif.
- `stats_objectifs()` : Calcule les statistiques globales du Progress Tracker (taux de complétion, etc.).
- `creer_snapshot_systeme(nom)` : Génère une archive locale de sauvegarde (.gos) via SyncSphere.
- `lister_snapshots_systeme()` : Liste l'ensemble des sauvegardes locales disponibles.
- `consulter_etat_maison(domaine)` : Retourne l'état en direct de la machine et des sous-systèmes GreatOS.
- `inspecter_architecture_greatos(module)` : Consulte la cartographie officielle des 8 modules du CDC.
- `consulter_historique_projet(nombre)` : Lit les dernières sessions d'apprentissage enregistrées.
- `executer_workflow_preconfigure(identifiant)` : Lance un workflow préconfiguré TaskFlow (ex: session_dev, nettoyage_systeme).
- `arbitrer_priorite_taches(taches)` : Évalue et classe des tâches selon la matrice multi-critères (urgence, importance, effort).
- `capturer_contexte_quadridimensionnel()` : Évalue le contexte selon les 4 dimensions (temporelle, cognitive, opérationnelle, spatiale).
- `charger_etat_gamification()` : Consulte les points XP, niveau et badges de l'utilisateur.

## Principes a conserver

- Ne pas ajouter d'outil sans l'exposer dans `tools.OUTILS`.
- Ne pas maintenir une liste statique des outils dans le prompt : `core/tool_signatures.py` introspecte le registre actif.
- Ne pas laisser une capability appeler le LLM.
- Ne pas contourner `tools.py` pour une action exposee a Jarvis.
- Ne pas introduire de confirmation interactive dans Stark.
- Garder les outils automatisables separes des outils sensibles ou bloquants.
