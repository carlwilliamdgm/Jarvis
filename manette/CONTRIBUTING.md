# Contribuer à PHANTOM by The Great Corporation

Merci pour votre intérêt envers **PHANTOM**, le projet de contrôleur virtuel d'élite signé **The Great Corporation (TGC)**.  
Nous concevons des logiciels guidés par un principe absolu : **Satisfaction > Coût**.

Ce document définit les normes d'ingénierie, les flux Git et les standards de code appliqués sur ce dépôt.

---

## 🧭 Principes Directeurs

1. **Zéro-Régression de Latence** : Toute modification sur le pipeline réseau (UDP / WebSocket) ou sur le dispatcher d'inputs doit préserver la performance sub-milliseconde.
2. **Isolation Matérielle Stricte** : Chaque contact tactile (`pointerId`) sur l'application mobile doit demeurer totalement étanche pour ne jamais perturber les autres canaux.
3. **Zéro-Friction Utilisateur** : Aucun changement ne doit complexifier l'installation ou imposer à l'utilisateur final des configurations manuelles obscures.

---

## 🌿 Stratégie de Branches

* **`main`** : Branche principale protégée, toujours stable et prête pour le déploiement en production.
* **`correction-manette`** : Branche de staging / pré-production pour l'intégration des correctifs.
* **Branches de fonctionnalités** : `feat/<nom>`, `fix/<nom>`, `docs/<nom>`, `perf/<nom>`.

---

## 📜 Conventions de Commits (Conventional Commits)

Nous suivons rigoureusement la spécification standard **Conventional Commits** :

```
<type>(<périmètre>): <description concise à l'impératif>

[corps de texte explicatif optionnel]
```

### Types autorisés :
* `feat` : Nouvelle fonctionnalité utilisateur.
* `fix` : Correction d'anomalie ou de bug.
* `perf` : Optimisation de latence, de débit ou de mémoire.
* `docs` : Évolution ou création de documentation.
* `test` : Ajout ou révision de tests automatisés.
* `refactor` : Réorganisation du code sans impact fonctionnel.
* `chore` : Maintenance de l'outillage ou des dépendances.

---

## 💻 Environnement de Développement Local

### 1. Serveur PC (Python 3.12)
1. Clonez le dépôt :
   ```bash
   git clone https://github.com/The-Great-Corporation/PHANTOM-by-The-Great-Corporation.git
   cd PHANTOM-by-The-Great-Corporation
   ```
2. Exécutez l'installeur pré-vol automatisé :
   ```powershell
   .\install.ps1
   ```
3. Exécutez les tests de validation :
   ```powershell
   .\.venv\Scripts\python.exe -m pytest server/tests
   ```

### 2. Application Mobile (Android / Kotlin)
1. Ouvrez le dossier `android/` dans **Android Studio** (Koala ou version ultérieure).
2. Vérifiez la présence du JDK 17 (`JAVA_HOME`).
3. Lancez les tests unitaires :
   ```bash
   ./gradlew test
   ```

---

## 🧪 Exigences Relatives aux Tests

* Aucun commit ne sera fusionné sur `main` si la suite de tests échoue.
* Tout correctif de bug doit être accompagné d'un test unitaire reproduisant l'anomalie résolue.
* La suite complète de 54 tests serveur doit rester à 100 % de réussite.

---

## 🔒 Confidentialité & Sécurité

Pour tout signalement de vulnérabilité de sécurité, veuillez suivre la procédure décrite dans [`SECURITY.md`](SECURITY.md) et ne jamais ouvrir d'issue publique.

---
*The Great Corporation™ — Tous droits réservés.*
