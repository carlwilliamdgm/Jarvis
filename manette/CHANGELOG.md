# Journal des Modifications (Changelog)

Toutes les modifications notables apportées au projet **PHANTOM by The Great Corporation** sont consignées dans ce document.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/), et ce projet adhère à la spécification [Semantic Versioning](https://semver.org/lang/fr/).

---

## [1.0.0-RC1] - 2026-09-25

### 👑 Lancement Commercial Initial — Édition Signature TGC

#### ✨ Ajouts majeurs (Mobile Android)
* **Moteur Tactile Indépendant** : Isolation stricte de chaque contact tactile (`pointerId`) éliminant toute interférence entre les boutons d'action (A, B, X, Y), les gâchettes et les axes directionnels.
* **Stick Flottant à Ancre Suiveuse (*Following Anchor*)** : Réalignement dynamique continu du centre du joystick dès que le pouce dépasse la zone maximale de course.
* **Commutateur de Mode Stick Gauche** : Possibilité de basculer à chaud entre mode *Flottant* et mode *Fixe* depuis le *Quick Settings Drawer* en cours de jeu et dans le *Studio de Configuration*.
* **Studio de Configuration Haute Couture** :
  * Thèmes visuels interchangeables (Xbox Series, PlayStation DualSense, Nintendo Switch Pro, Cyberpunk Neon, Ghost Minimalist).
  * Importateur de fonds d'écran et GIFs animés depuis la galerie Android avec curseur d'assombrissement immersif.
  * Réglage de sensibilité et deadzones avec persistance dans les profils utilisateur.
* **Auto-Discovery Zéro-Friction** : Détection automatique instantanée du serveur PC sur le réseau Wi-Fi local sans saisie manuelle d'adresse IP.
* **Mode Universel « Plug & Play »** : Émulation autonome manette Bluetooth HID sans aucun logiciel tiers sur la machine hôte.

#### ⚡ Ajouts majeurs (Serveur PC Windows)
* **Scanner de Paysage Pré-Vol (`landscape_scanner.py`)** : Diagnostic automatique en 5 phases vérifiant l'environnement virtuel `.venv`, le pilote `ViGEmBus`, la disponibilité des ports (`8888`, `8889`, `8890`, `8887`), le pont ADB et l'IP locale.
* **Protection Mutex Windows Système** : Verrouillage atomique nommé (`Global\PhantomServerTGC_SingleInstance_Mutex`) interdisant les conflits d'instances concurrentes.
* **Installeur Assisté 1-Clic (`install.ps1`)** : Déploiement automatique, installation des dépendances et génération du raccourci Bureau « PHANTOM Server TGC ».
* **Lanceur Autonome (`Lancer_Serveur_Phantom_TGC.bat`)** : Démarrage direct ciblant l'environnement `.venv` sans aucune commande console requise.
* **Sécurité & Intégrité** : Échange de jetons cryptographiques de session HMAC-SHA256 pour sécuriser les trames UDP d'inputs.
* **Émulation Matérielle ViGEmBus** : Émulation native des manettes Xbox 360 et Sony DualShock 4 au niveau du noyau Windows.

#### 🧪 Assurance Qualité & Documentation
* 54 tests automatisés passés avec succès à 100 % sur la suite serveur (`pytest server/tests`).
* Validation des tests unitaires Android sous Gradle 8.14.5 et Kotlin 1.9+.
* Intégration de la licence commerciale propriétaire [TGC Proprietary Commercial License (EULA)](LICENSE).
* Révision complète des guides d'installation, d'utilisation et de dépannage dans [`docs/`](docs/).

---

*Copyright © 2026 The Great Corporation. Tous droits réservés.*
