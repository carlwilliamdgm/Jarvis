"""
Tests pour le Registre d'Autonomie Progressive (Trust Matrix) - Jalon 5.

Valide le système à 4 niveaux d'autonomie, le mécanisme à cliquet (promotion/rétrogradation),
l'extraction de domaines, et l'isolation multi-utilisateurs.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_engine.trust_registry import (
    extraire_domaine_capacite,
    obtenir_niveau_autonomie,
    doit_confirmer_action,
    enregistrer_resultat_action,
    obtenir_resume_confiance_compact,
    NIVEAU_OBSERVATION,
    NIVEAU_PROPOSITION,
    NIVEAU_ACTION_NOTIFICATION,
    NIVEAU_AUTONOMIE_SILENCIEUSE,
    SEUIL_PROMOTION,
    PROFILES_DIR,
)


class TestTrustRegistry(unittest.TestCase):
    def setUp(self):
        """Nettoie le dossier des profils avant chaque test."""
        # Sauvegarder le PROFILES_DIR original
        self.original_dir = PROFILES_DIR
        
        # Utiliser un dossier temporaire pour les tests
        import context_engine.trust_registry as trust_registry_module
        self.temp_dir = Path(tempfile.mkdtemp())
        trust_registry_module.PROFILES_DIR = self.temp_dir
    
    def tearDown(self):
        """Nettoie le dossier temporaire après chaque test."""
        import context_engine.trust_registry as trust_registry_module
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        trust_registry_module.PROFILES_DIR = self.original_dir

    def test_extraire_domaine_capacite_fichiers(self):
        """Teste l'extraction de domaine pour les capacités fichiers."""
        self.assertEqual(extraire_domaine_capacite("fichiers.lire"), "fichiers_lire")
        self.assertEqual(extraire_domaine_capacite("fichiers.ecrire"), "fichiers_ecrire")
        self.assertEqual(extraire_domaine_capacite("fichiers.supprimer"), "fichiers_supprimer")
    
    def test_extraire_domaine_capacite_systeme(self):
        """Teste l'extraction de domaine pour les capacités système."""
        self.assertEqual(extraire_domaine_capacite("systeme.commande"), "systeme_commande")
        self.assertEqual(extraire_domaine_capacite("systeme.reboot"), "systeme_reboot")
    
    def test_extraire_domaine_capacite_web(self):
        """Teste l'extraction de domaine pour les capacités web."""
        self.assertEqual(extraire_domaine_capacite("web.recherche"), "web_recherche")
        self.assertEqual(extraire_domaine_capacite("web.telecharger"), "web_telecharger")
    
    def test_extraire_domaine_capacite_caracteres_speciaux(self):
        """Teste l'extraction avec caractères spéciaux."""
        self.assertEqual(extraire_domaine_capacite("fichiers.lire-fichier"), "fichiers_lire_fichier")
        self.assertEqual(extraire_domaine_capacite("systeme@commande"), "systeme_commande")
    
    def test_extraire_domaine_capacite_vide(self):
        """Teste l'extraction avec une capacité vide."""
        self.assertEqual(extraire_domaine_capacite(""), "inconnu")
        self.assertEqual(extraire_domaine_capacite(None), "inconnu")
    
    def test_obtenir_niveau_autonomie_domaine_inconnu(self):
        """Teste qu'un domaine inconnu retourne le niveau 0."""
        niveau = obtenir_niveau_autonomie("domaine_inconnu", "alice")
        self.assertEqual(niveau, NIVEAU_OBSERVATION)
    
    def test_obtenir_niveau_autonomie_sans_user_id(self):
        """Teste la résolution dynamique de l'utilisateur."""
        with patch.dict(os.environ, {"GREATOS_USER": "testuser"}):
            niveau = obtenir_niveau_autonomie("fichiers_lire")
            self.assertEqual(niveau, NIVEAU_OBSERVATION)
    
    def test_doit_confirmer_action_niveau_0(self):
        """Teste que le niveau 0 requiert une confirmation."""
        # Par défaut, niveau 0
        self.assertTrue(doit_confirmer_action("fichiers.lire", "bob"))
    
    def test_doit_confirmer_action_niveau_1(self):
        """Teste que le niveau 1 requiert une confirmation."""
        # Enregistrer des succès pour atteindre le niveau 1
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("fichiers.lire", True, "charlie")
        
        # Niveau 1 = confirmation requise
        self.assertTrue(doit_confirmer_action("fichiers.lire", "charlie"))
    
    def test_doit_confirmer_action_niveau_2(self):
        """Teste que le niveau 2 ne requiert pas de confirmation."""
        # Atteindre le niveau 2
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("systeme.commande", True, "diane")
        
        # Niveau 2 = pas de confirmation
        self.assertFalse(doit_confirmer_action("systeme.commande", "diane"))
    
    def test_doit_confirmer_action_niveau_3(self):
        """Teste que le niveau 3 ne requiert pas de confirmation."""
        # Atteindre le niveau 3
        for _ in range(SEUIL_PROMOTION * 3):
            enregistrer_resultat_action("web.recherche", True, "eve")
        
        # Niveau 3 = pas de confirmation
        self.assertFalse(doit_confirmer_action("web.recherche", "eve"))
    
    def test_enregistrer_resultat_action_premier_succes(self):
        """Teste l'enregistrement du premier succès."""
        etat = enregistrer_resultat_action("fichiers.lire", True, "frank")
        
        self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
        self.assertEqual(etat["succes_consecutifs"], 1)
        self.assertEqual(etat["actions_totales"], 1)
        self.assertEqual(etat["echecs"], 0)
        self.assertEqual(etat["score"], 1.0)
    
    def test_enregistrer_resultat_action_premier_echec(self):
        """Teste l'enregistrement du premier échec."""
        etat = enregistrer_resultat_action("fichiers.lire", False, "grace")
        
        self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
        self.assertEqual(etat["succes_consecutifs"], 0)
        self.assertEqual(etat["actions_totales"], 1)
        self.assertEqual(etat["echecs"], 1)
        self.assertEqual(etat["score"], 0.0)
    
    def test_promotion_apres_seuil_succes(self):
        """Teste la promotion après N succès consécutifs."""
        # Enregistrer SEUIL_PROMOTION - 1 succès
        for i in range(SEUIL_PROMOTION - 1):
            etat = enregistrer_resultat_action("fichiers.ecrire", True, "henry")
            self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
        
        # Le dernier succès devrait promouvoir au niveau 1
        etat = enregistrer_resultat_action("fichiers.ecrire", True, "henry")
        self.assertEqual(etat["niveau"], NIVEAU_PROPOSITION)
        self.assertEqual(etat["succes_consecutifs"], 0)  # Réinitialisé après promotion
    
    def test_promotion_multiple_niveaux(self):
        """Teste la promotion à travers plusieurs niveaux."""
        # Promouvoir au niveau 1
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("systeme.reboot", True, "isaac")
        
        niveau = obtenir_niveau_autonomie("systeme_reboot", "isaac")
        self.assertEqual(niveau, NIVEAU_PROPOSITION)
        
        # Promouvoir au niveau 2
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("systeme.reboot", True, "isaac")
        
        niveau = obtenir_niveau_autonomie("systeme_reboot", "isaac")
        self.assertEqual(niveau, NIVEAU_ACTION_NOTIFICATION)
        
        # Promouvoir au niveau 3
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("systeme.reboot", True, "isaac")
        
        niveau = obtenir_niveau_autonomie("systeme_reboot", "isaac")
        self.assertEqual(niveau, NIVEAU_AUTONOMIE_SILENCIEUSE)
    
    def test_retrogradation_immediate_apres_echec(self):
        """Teste la rétrogradation immédiate après un échec."""
        # Atteindre le niveau 2
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("web.telecharger", True, "julia")
        
        niveau = obtenir_niveau_autonomie("web_telecharger", "julia")
        self.assertEqual(niveau, NIVEAU_ACTION_NOTIFICATION)
        
        # Un échec devrait rétrograder au niveau 1
        etat = enregistrer_resultat_action("web.telecharger", False, "julia")
        self.assertEqual(etat["niveau"], NIVEAU_PROPOSITION)
        self.assertEqual(etat["succes_consecutifs"], 0)
        self.assertEqual(etat["echecs"], 1)
    
    def test_retrogradation_depuis_niveau_0(self):
        """Teste qu'on ne peut pas rétrograder en dessous du niveau 0."""
        # Échec au niveau 0
        etat = enregistrer_resultat_action("fichiers.lire", False, "karen")
        self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
        
        # Autre échec
        etat = enregistrer_resultat_action("fichiers.lire", False, "karen")
        self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
    
    def test_retrogradation_apres_promotion_partielle(self):
        """Teste la rétrogradation quand les succès consécutifs sont partiels."""
        # Quelques succès mais pas assez pour promouvoir
        for _ in range(SEUIL_PROMOTION - 2):
            enregistrer_resultat_action("fichiers.supprimer", True, "leo")
        
        etat = enregistrer_resultat_action("fichiers.supprimer", True, "leo")
        self.assertEqual(etat["succes_consecutifs"], SEUIL_PROMOTION - 1)
        
        # Un échec réinitialise les succès consécutifs
        etat = enregistrer_resultat_action("fichiers.supprimer", False, "leo")
        self.assertEqual(etat["succes_consecutifs"], 0)
        self.assertEqual(etat["niveau"], NIVEAU_OBSERVATION)
    
    def test_score_calcul_correct(self):
        """Teste le calcul du score de confiance."""
        # 5 succès, 0 échecs
        for _ in range(5):
            enregistrer_resultat_action("test.domaine", True, "martin")
        
        etat = enregistrer_resultat_action("test.domaine", True, "martin")
        self.assertEqual(etat["score"], 1.0)
        
        # 1 échec (7 total actions, 1 échec)
        etat = enregistrer_resultat_action("test.domaine", False, "martin")
        self.assertAlmostEqual(etat["score"], 6.0 / 7.0, places=2)
    
    def test_isolation_multi_utilisateurs(self):
        """Teste que la confiance d'Alice n'influence pas Bob."""
        # Alice atteint le niveau 2
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("fichiers.lire", True, "alice")
        
        niveau_alice = obtenir_niveau_autonomie("fichiers_lire", "alice")
        self.assertEqual(niveau_alice, NIVEAU_ACTION_NOTIFICATION)
        
        # Bob reste au niveau 0
        niveau_bob = obtenir_niveau_autonomie("fichiers_lecture", "bob")
        self.assertEqual(niveau_bob, NIVEAU_OBSERVATION)
    
    def test_isolation_fichiers_multi_utilisateurs(self):
        """Teste que les fichiers trust_matrix sont isolés par utilisateur."""
        import context_engine.trust_registry as trust_registry_module
        
        enregistrer_resultat_action("fichiers.lire", True, "nora")
        enregistrer_resultat_action("fichiers.lire", True, "oscar")
        
        chemin_nora = trust_registry_module._chemin_trust_matrix("nora")
        chemin_oscar = trust_registry_module._chemin_trust_matrix("oscar")
        
        self.assertTrue(chemin_nora.exists())
        self.assertTrue(chemin_oscar.exists())
        self.assertNotEqual(chemin_nora, chemin_oscar)
    
    def test_obtenir_resume_confiance_compact_vide(self):
        """Teste le résumé quand aucun domaine n'est suivi."""
        resume = obtenir_resume_confiance_compact("paul")
        
        self.assertIn("Matrice de Confiance", resume)
        self.assertIn("Aucun domaine suivi", resume)
    
    def test_obtenir_resume_confiance_compact_avec_domaines(self):
        """Teste le résumé avec plusieurs domaines."""
        # Ajouter des domaines avec différents niveaux
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("fichiers.lire", True, "quinn")
        
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("systeme.commande", True, "quinn")
        
        resume = obtenir_resume_confiance_compact("quinn")
        
        self.assertIn("Matrice de Confiance", resume)
        self.assertIn("fichiers_lire", resume)
        self.assertIn("systeme_commande", resume)
        self.assertIn("Niveau 1", resume)
        self.assertIn("Niveau 2", resume)
        self.assertIn("Score:", resume)
        self.assertIn("Succès consécutifs:", resume)
    
    def test_persistence_sur_disque(self):
        """Teste que les données sont persistées sur disque."""
        import context_engine.trust_registry as trust_registry_module
        
        # Enregistrer des actions
        for _ in range(3):
            enregistrer_resultat_action("fichiers.lire", True, "rachel")
        
        # Charger directement depuis le fichier
        chemin = trust_registry_module._chemin_trust_matrix("rachel")
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.assertIn("fichiers_lire", data["domaines"])
        self.assertEqual(data["domaines"]["fichiers_lire"]["actions_totales"], 3)
    
    def test_fichier_corrompu_recree(self):
        """Teste qu'un fichier corrompu entraîne la recréation de la matrice."""
        import context_engine.trust_registry as trust_registry_module
        
        # Créer un fichier corrompu
        chemin = trust_registry_module._chemin_trust_matrix("sam")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("{invalid json content")
        
        # Charger devrait recréer la matrice
        niveau = obtenir_niveau_autonomie("fichiers_lire", "sam")
        self.assertEqual(niveau, NIVEAU_OBSERVATION)
    
    def test_domaines_multiples_par_utilisateur(self):
        """Teste qu'un utilisateur peut avoir plusieurs domaines suivis."""
        # Ajouter des actions dans différents domaines
        for _ in range(SEUIL_PROMOTION):
            enregistrer_resultat_action("fichiers.lire", True, "tina")
        
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("web.recherche", True, "tina")
        
        for _ in range(2):
            enregistrer_resultat_action("systeme.commande", True, "tina")
        
        # Vérifier que chaque domaine a le bon niveau
        self.assertEqual(
            obtenir_niveau_autonomie("fichiers_lire", "tina"),
            NIVEAU_PROPOSITION
        )
        self.assertEqual(
            obtenir_niveau_autonomie("web_recherche", "tina"),
            NIVEAU_ACTION_NOTIFICATION
        )
        self.assertEqual(
            obtenir_niveau_autonomie("systeme_commande", "tina"),
            NIVEAU_OBSERVATION
        )
    
    def test_echec_ne_retrograde_pas_autres_domaines(self):
        """Teste qu'un échec dans un domaine n'affecte pas les autres."""
        # Atteindre niveau 2 dans deux domaines
        for _ in range(SEUIL_PROMOTION * 2):
            enregistrer_resultat_action("fichiers.lire", True, "uma")
            enregistrer_resultat_action("web.recherche", True, "uma")
        
        # Échec dans un seul domaine
        enregistrer_resultat_action("fichiers.lire", False, "uma")
        
        # Vérifier que seul le premier domaine a rétrogradé
        self.assertEqual(
            obtenir_niveau_autonomie("fichiers_lire", "uma"),
            NIVEAU_PROPOSITION
        )
        self.assertEqual(
            obtenir_niveau_autonomie("web_recherche", "uma"),
            NIVEAU_ACTION_NOTIFICATION
        )


if __name__ == "__main__":
    unittest.main()
