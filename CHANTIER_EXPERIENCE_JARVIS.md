# Chantier : expérience J.A.R.V.I.S. de bout en bout

**Statut :** cadrage proposé
**Périmètre :** intégration GreatOS avec les capacités de Windows et des fournisseurs configurés
**Principe :** GreatOS est une surcouche. Il suit les choix de l'OS hôte et orchestre ses capacités au lieu de réimplémenter les fonctions que l'OS fournit déjà.

## Objectif

Rendre fiable et cohérent le parcours complet : mot de réveil → écoute → compréhension → perception/commande Windows → réponse vocale → retour au HUD et à l'écoute. Le chantier vise une expérience inspirée de J.A.R.V.I.S.; il ne suppose pas que toutes les capacités fictives de l'univers Marvel soient réalisables.

## État établi dans le code

- Le serveur démarre le HUD vocal et le listener si l'écoute n'est pas désactivée et qu'un périphérique d'entrée est détecté.
- Le HUD lit `runtime/voice_state.json`; le moteur publie les états et le texte transcrit.
- Le moteur vocal implémente le réveil, une fenêtre d'écoute de 25 secondes et le retour aux états d'écoute/veille.
- Le microphone est choisi depuis le périphérique par défaut exposé par PortAudio/Windows. GreatOS ne doit pas lui substituer une sélection propre. Le choix est résolu à l'ouverture du moteur; un changement de défaut pendant l'exécution doit être pris en charge ou clairement signalé.
- `context_engine.desktop_vision` capture l'écran Windows et tente une analyse Groq. En l'absence de fournisseur utilisable, il ne sait pas interpréter les pixels localement.
- Les commandes Windows existent dans `taskflow/windows_actions.py` et `taskflow/tools.py` : volume/multimédia, lancement d'applications, fenêtres, capture/analyse écran. Leurs retours doivent être vérifiés contre l'effet réellement obtenu.
- `CHANTIER_AUTONOMIE_GOUVERNANCE.md` couvre déjà DataShield, la Trust Matrix et les confirmations. Le présent chantier s'y intègre et ne redéfinit pas la politique de sécurité.

## Lots proposés

### Avancement du lot 1

- **Implémenté dans le dépôt :** le moteur audio suit le défaut d'entrée PortAudio/Windows, surveille le défaut environ chaque seconde, ferme l'ancien flux et rouvre un seul flux sur le nouveau périphérique. Les écouteurs restent en attente si aucun défaut n'est disponible au lancement.
- **Diagnostic ajouté :** `/jarvis/status` indique le défaut détecté (nom, backend hôte), le périphérique actif, l'état du flux et la raison d'indisponibilité de l'écoute.
- **Correction runtime :** `sounddevice.default.device` est un objet `_InputOutputPair` indexable, pas forcément une liste ou un tuple. L'ancienne lecture pouvait donc manquer le défaut; l'extraction par index est maintenant prise en charge. La lecture locale de l'hôte a identifié le défaut d'entrée à l'index 1 via MME.
- **À valider avant clôture :** vérifier sur Windows le basculement machine ↔ casque Bluetooth, l'absence de double flux et la mise à jour du statut. Le code ne vaut pas preuve du comportement des pilotes audio du poste.

### Avancement du lot 2

- **Implémenté dans le dépôt :** le HUD montre le micro hôte en veille; les statuts vocaux détaillent l'entrée audio; les commentaires et journaux du délai d'écoute sont harmonisés sur 25 secondes.
- **Correction anti-écho :** après une réponse Edge-TTS jouée par Windows, GreatOS vide la capture accumulée et applique la garde audio avant de reprendre l'écoute. Le chemin Piper gardait déjà cette garde.
- **À valider avant clôture :** observer sur le poste les transitions HUD et vérifier qu'une réponse TTS n'est pas retranscrite comme une nouvelle commande.

### Avancement du lot 3

- **Correction réalisée :** les retours des commandes multimédias et volume indiquent maintenant que la touche a été envoyée à Windows, sans prétendre que le volume ou la lecture ont changé; les erreurs Python d'envoi sont rapportées.
- **Correction réalisée :** `minimiser_tout` consulte le code de sortie PowerShell et signale un échec au lieu de déclarer les fenêtres minimisées sans contrôle.
- **Limite connue :** `keybd_event` ne fournit pas de confirmation de l'effet final. Le retour utilisateur reste donc honnête (« commande envoyée; effet non confirmé »). MoveWindow, lui, fournit déjà un booléen de succès Win32.
- **À poursuivre :** vérifier les comportements au bureau interactif, statuer sur la confirmation de LockWorkStation et rendre la disponibilité/cause de la vision plus explicite dans le trajet outil → voix/HUD.

### Revue globale du dépôt — 11 octobre 2026

- **Cartographie :** 171 modules Python et 56 fichiers Python sous `tests/`; huit domaines principaux existent, avec `greatos_capabilities.py` comme dispatcher, `jarvis/agent.py` comme orchestration, FastAPI comme surface HTTP, et `interface_morphique/server.py` comme démarrage officiel du HUD et des listeners.
- **Parcours vocal réel :** `lancer_jarvis.bat` appelle `greatos_service.py`, qui démarre `interface_morphique.server:app`; le serveur lance `jarvis.voice_input` et le HUD. `scripts/jarvis_live_daemon.py` existe encore, mais ce lanceur ne le démarre pas. La transcription tente Groq puis conserve le résultat Vosk local; les confirmations vocales ont également un repli Vosk.
- **Validation :** la présence des 56 fichiers de test ne signifie pas qu'ils sont tous verts. Les entrées du journal prouvent quelques contrôles statiques et diagnostics ciblés, pas un parcours matériel de bout en bout. Le changement de micro Windows, l'anti-écho sur haut-parleurs réels, le HUD et les actions physiques restent à valider sur la session utilisateur.
- **Sécurité API :** avant la revue, `verify_api_key` acceptait une adresse distante non approuvée si `JARVIS_API_KEY` était absente. Le code refuse maintenant ces demandes avec HTTP 503; localhost et le tailnet déclaré fiable gardent leur accès sans bearer. Valider cette règle sans exécuter toute la suite reste à faire.
- **Vision :** `/jarvis/status` expose maintenant les capacités configurées (capture locale prise en charge, configuration/bibliothèque Groq) tout en signalant que l'accès réel au bureau et la joignabilité du fournisseur ne sont pas prouvés par cette inspection. Les échecs de capture, de configuration et de service sont distingués dans le compte rendu d'analyse.
- **Déploiement :** `jarvis_hidden.ps1` écoute par défaut sur `127.0.0.1`; le script d'installation fournit explicitement `0.0.0.0` à la tâche. `update_scheduled_task.ps1` reconstruit l'action sans `-HostAddress`, donc son utilisation peut retirer l'accès tailnet prévu. Vérifier l'action effective de `JarvisAgent` sur la machine avant de changer le binding.
- **Ordre de suite proposé :** 1) contrôler les parcours vocal/HUD et la sélection de micro sur le Windows réel; 2) valider la politique de refus API hors localhost/tailnet sans clé; 3) consolider les preuves de résultat pour toutes les actions Windows; 4) effectuer le trajet vision/capture/fournisseur; 5) exécuter la suite de tests puis le parcours manuel et consigner les résultats.

### 1. Contrat hôte et diagnostic des capacités

- Utiliser le microphone par défaut de Windows; détecter les changements de périphérique et rouvrir le flux sans créer de flux audio concurrents.
- Vérifier le périphérique d'entrée par défaut réellement sélectionné, pas seulement la présence de n'importe quel microphone.
- Exposer dans le statut et le HUD les capacités disponibles : entrée audio, sortie audio, réveil local, STT local/en ligne, TTS local/en ligne, capture écran, moteur d'analyse visuelle, commandes Windows.
- Montrer clairement une capacité indisponible et sa cause, sans annoncer une action ou une analyse réussie à tort.

### 2. Parcours vocal et synchronisation du HUD

- Formaliser les transitions attendues : `IDLE → WAKING_UP → LISTENING → THINKING → ACTION/SPEAKING → LISTENING`, puis veille après 25 secondes de silence.
- Vérifier que l'anti-écho, le filtrage des faux réveils et les interruptions TTS restent actifs dans le chemin de lancement officiel.
- Synchroniser le texte partiel, les erreurs et les réponses avec le HUD; s'assurer qu'une panne du HUD ne bloque pas la voix.
- Garantir un unique moteur de capture partagé avec le wake word, la transcription et la confirmation vocale.

### 3. Yeux et mains Windows

- Consolider les commandes sûres déjà présentes et leurs alias vocaux : volume, médias, applications et fenêtres.
- Pour chaque commande, différencier succès vérifié, échec OS et capacité indisponible; ne pas répondre « effectué » si l'OS a refusé ou ignoré l'action.
- Pour la vision, séparer explicitement la capture écran (locale) de l'interprétation (fournisseur multimodal). Le repli local est un sous-lot conditionnel, à cadrer selon les modèles présents et les ressources de la machine.
- Tenir compte de la session Windows interactive : la capture d'écran et les actions de bureau doivent s'exécuter dans le contexte utilisateur approprié, pas dans une session de service isolée.

### 4. Orchestration et gouvernance

- Valider un trajet unique de la commande vocale jusqu'à l'outil, puis jusqu'au compte rendu TTS/HUD.
- Réutiliser les règles DataShield/Trust Matrix et le gestionnaire de confirmation multi-surface existants; garder les actions sûres fluides et les opérations sensibles soumises à la confirmation prévue.
- En cas d'ambiguïté, demander une précision; ne pas transformer une intention incertaine en action Windows.
- Préserver une voie textuelle de diagnostic quand le micro ou la synthèse est indisponible.

### 5. Validation d'acceptation

Automatiser les tests de contrat avec périphériques et API simulés, puis exécuter un parcours manuel sur le poste Windows réel. Aucun test automatisé ne peut remplacer la vérification du micro, du bureau interactif ou du rendu HUD sur l'hôte.

Parcours minimal :

1. Démarrer GreatOS et vérifier son statut, le HUD et les capacités détectées.
2. Vérifier que le micro utilisé est bien le défaut Windows; changer le défaut et constater la prise en compte selon le mécanisme de reconnexion retenu.
3. Dire « Jarvis », vérifier le réveil, l'écoute et la réponse vocale; attendre 25 secondes de silence et vérifier le retour en veille.
4. Demander une action sûre (baisser le volume ou changer de média) et constater l'effet Windows ainsi que le compte rendu HUD/TTS.
5. Demander une analyse d'écran et vérifier la capture, l'interprétation et le comportement explicite si le fournisseur de vision est indisponible.
6. Vérifier qu'une action sensible suit la confirmation vocale prévue et qu'un refus/timeout ne l'exécute pas.
7. Vérifier qu'une perte réseau conserve les capacités locales annoncées et que les capacités dépendantes du réseau échouent proprement.

## Critères de fin

- Aucun périphérique d'entrée choisi arbitrairement par GreatOS : le défaut Windows est utilisé et son indisponibilité est visible.
- Les transitions vocales et le HUD concordent sur le parcours complet, sans blocage du thread de capture.
- Une action Windows n'est annoncée comme réussie qu'après succès de son appel OS ou vérification de son effet.
- La vision distingue la capture locale de l'analyse distante ou locale et indique honnêtement ses dépendances.
- Les tests automatisés des contrats passent; le parcours d'acceptation Windows est consigné avec résultat et limites restantes.
- La politique de sécurité existante reste intacte; toute modification au chantier Autonomie & Gouvernance est tracée séparément.

## Ordre de travail recommandé

1. Inventorier les chemins réels de démarrage et corriger les écarts de statut/capacité.
2. Fiabiliser le défaut micro Windows et la reconnexion, puis le cycle vocal/HUD.
3. Vérifier les commandes Windows et leurs retours réels.
4. Rendre la vision honnête et résiliente; décider séparément si un modèle visuel local est justifié.
5. Exécuter et consigner le parcours complet d'acceptation.

## Hors périmètre immédiat

- Réécrire les services audio/Windows déjà fournis par l'OS.
- Ajouter un modèle de vision local sans mesurer son coût, sa latence et sa compatibilité matérielle.
- Affaiblir DataShield ou contourner les confirmations sensibles pour obtenir une impression d'autonomie.
