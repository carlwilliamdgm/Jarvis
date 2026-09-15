# État des lieux — GreatOS

**Date de révision :** septembre 2026

**Statut global :** prototype local-first avancé, en phase de stabilisation / release candidate surveillée.
**Source de vérité :** le code et les tests du dépôt. Le [cahier des charges](Documents/CAHIER_DES_CHARGES.md) décrit la cible, pas l'état de livraison.

## Résumé

GreatOS est une surcouche intelligente personnelle pour Windows, composée de huit modules Python. Jarvis est utilisable en texte et en voix ; il dispose d'une cascade LLM, d'outils locaux, d'automatisations, d'une API FastAPI et d'interfaces web/HUD.

Les correctifs de stabilisation récents ont limité la latence des fournisseurs locaux, évité des cascades cloud excessives, amélioré la résilience de la capture vocale et suspendu l'agent autonome pendant une interaction utilisateur. Les suites ciblées de stabilité et de sécurité exécutées lors de cette révision sont vertes.

Le projet ne doit pas encore être présenté comme une implémentation complète des critères PFE 2028 ou de la vision 2033.

## Modules : état réel

| Module | Disponible aujourd'hui | Limites et éléments à réaliser |
|---|---|---|
| **Jarvis** | Conversation texte/voix, wake word Vosk, double-clap, Piper TTS, mémoire de session, Mode Stark, orchestration des outils. | Les objectifs NLU >80 %, réponse <2 s à 95 % et mémoire conversationnelle illimitée ne sont pas mesurés ni garantis. |
| **Core Intellect** | Cascade Groq / OpenRouter / Jarvis-GC / Ollama, analyse d'intention, outils connus, gestion de réponses LLM dégradées. | Pas de Random Forest ni Knowledge Graph démontré ; qualité des recommandations non mesurée. |
| **Context Engine** | Mémoire JSON/SQLite, état système, suggestions, recherche sémantique et détection de patterns simples. | Pas de hooks OS complets, LSTM ni prédiction temporelle avancée. |
| **TaskFlow** | Outils fichiers, commandes, web, navigateur, calendrier/email, workflows et automatisations planifiées. | Les intégrations externes annoncées ne sont pas toutes validées ; les politiques de sécurité doivent encore être davantage centralisées. |
| **Progress Tracker** | Objectifs, suivi persistant et analytics de base. | Dashboard complet, gamification, ARIMA et visualisations avancées ne sont pas établis. |
| **DataShield** | DEFCON, protections de chemins, confirmations, classification d'erreurs et autodestruction contrôlée. | Chiffrement AES-256-GCM, SQLCipher, Argon2id, 2FA/TOTP et détection ML ne sont pas implémentés. |
| **SyncSphere** | Snapshots locaux `.gos`, liste et restauration. | Les snapshots sont des archives `tar.gz`, pas des sauvegardes chiffrées ; pas de synchronisation multi-appareils. |
| **Interface Morphique** | API FastAPI, SSE, interface web HTML/JS, interface Tkinter et HUDs vocaux/navigateur. | Pas d'Electron, React, Tailwind ni de huit layouts contextuels démontrés. |

## Architecture et responsabilités

L'architecture opérationnelle actuelle est :

```text
Interfaces (web, Tkinter, voix, CLI)
             ↓
Jarvis : orchestration des interactions
             ↓
Core Intellect : interprétation et décision
             ↓
TaskFlow : exécution des outils
             ↓
DataShield : règles de zones, DEFCON et confirmations
             ↓
Windows, fichiers, réseau et services locaux
```

DataShield est le socle de politique de sécurité, mais son application n'est pas encore entièrement centralisée : TaskFlow porte aussi des contrôles de commandes, l'API gère son authentification dans `interface_morphique`, et SyncSphere restaure directement les snapshots. Une évolution souhaitée est que chaque action passe par une décision uniforme de DataShield : **autoriser**, **demander confirmation** ou **bloquer**.

## Modèle de sécurité actuel

- Jarvis et le Mode Stark s'exécutent avec les droits du compte Windows courant ; aucune élévation UAC ne doit être tentée automatiquement.
- Les zones Windows, Program Files et le dossier GreatOS/Jarvis sont protégés par confirmation dans les flux d'outils concernés.
- Les actions réversibles refusées par le filtre standard peuvent demander une confirmation unique ; les opérations irréversibles restent bloquées.
- DEFCON 1 et 2 restent des modes d'urgence bloquants. DEFCON 3 impose une confirmation pour les commandes système.
- L'API accepte un Bearer token seulement lorsque `JARVIS_API_KEY` est configurée. Sans cette variable, elle est ouverte : elle doit rester locale ou restreinte à un réseau privé contrôlé.
- Le Mode Stark est volontairement autonome : il réduit les confirmations mais reste limité aux droits Windows du compte courant.

## Stabilisation et validation

Les correctifs récents couvrent notamment :

- timeouts Ollama et Jarvis-GC à 15 s par défaut ;
- retour immédiat après timeout d'une inférence locale ;
- une réponse LLM textuelle convertie en réponse conversationnelle plutôt qu'en échec de cascade ;
- une queue de transcription à 64 trames avec éviction des données les plus anciennes et limitation des logs de saturation ;
- suspension de l'agent autonome pendant une interaction ;
- confirmation unique pour les commandes réversibles filtrées, comme un redémarrage.

Les tests ciblés LLM, audio, noyau, DataShield, TaskFlow et durcissement passent lors de cette révision. Cela ne remplace pas une validation de production complète.

## Avant une déclaration « production-ready »

1. Exécuter une suite complète de non-régression et publier son résultat.
2. Faire un test vocal prolongé sur la machine cible, avec consultation des logs et mesure de la latence.
3. Mesurer les objectifs annoncés : latence p95, consommation CPU/RAM, taux de reconnaissance et taux d'échec des outils.
4. Configurer explicitement le fournisseur OpenRouter retenu et `JARVIS_API_KEY` si l'API est accessible hors de localhost.
5. Centraliser la décision de sécurité dans DataShield et chiffrer les données/snapshots avant de revendiquer les contrôles cryptographiques du cahier des charges.

## Portée plateforme

La version actuelle est principalement **Windows**. Les références à macOS, Linux, applications mobiles, API publique, éditions commerciales, E2EE multi-appareils et conformité (RGPD, ISO 27001, SOC 2) relèvent de la roadmap et ne sont pas livrées dans ce dépôt.
