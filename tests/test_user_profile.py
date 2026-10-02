"""
Tests pour le moteur de profil multi-utilisateurs (Jalon 2).

Valide la résolution dynamique de l'utilisateur, l'isolation des profils sur disque,
et les fonctions du contrat d'interface.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_engine.user_profile import (
    resoudre_utilisateur_actif,
    charger_profil,
    sauvegarder_profil,
    mettre_a_jour_directive_profil,
    obtenir_contexte_profil_compact,
    _slug_user_id,
    _profil_par_defaut,
    _chemin_profil,
    PROFILES_DIR,
)


class TestUserProfile(unittest.TestCase):
    def setUp(self):
        """Nettoie le dossier des profils avant chaque test."""
        # Sauvegarder le PROFILES_DIR original
        self.original_dir = PROFILES_DIR
        
        # Utiliser un dossier temporaire pour les tests
        import context_engine.user_profile as user_profile_module
        self.temp_dir = Path(tempfile.mkdtemp())
        user_profile_module.PROFILES_DIR = self.temp_dir
    
    def tearDown(self):
        """Nettoie le dossier temporaire après chaque test."""
        import context_engine.user_profile as user_profile_module
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        user_profile_module.PROFILES_DIR = self.original_dir


    def test_slug_user_id_caracteres_speciaux(self):
        """Teste le nettoyage des user_id avec caractères spéciaux."""
        self.assertEqual(_slug_user_id("Alice Dupont"), "Alice_Dupont")
        self.assertEqual(_slug_user_id("bob@company.com"), "bob_company_com")
        self.assertEqual(_slug_user_id("jean-pierre"), "jean-pierre")
        self.assertEqual(_slug_user_id("  espaces  "), "espaces")
        self.assertEqual(_slug_user_id(""), "default")
        self.assertEqual(_slug_user_id("!!!"), "default")

    def test_resoudre_utilisateur_actif_explicite(self):
        """Teste la résolution avec un user_id explicite."""
        user_id = resoudre_utilisateur_actif("Alice")
        self.assertEqual(user_id, "Alice")
        
        user_id = resoudre_utilisateur_actif("Bob Martin")
        self.assertEqual(user_id, "Bob_Martin")

    def test_resoudre_utilisateur_actif_env_var(self):
        """Teste la résolution via variable d'environnement GREATOS_USER."""
        with patch.dict(os.environ, {"GREATOS_USER": "testuser"}):
            user_id = resoudre_utilisateur_actif()
            self.assertEqual(user_id, "testuser")

    def test_resoudre_utilisateur_actif_os_user(self):
        """Teste la résolution via utilisateur de l'OS."""
        # Mock getpass.getuser
        with patch("context_engine.user_profile.getpass.getuser", return_value="osuser"):
            with patch.dict(os.environ, {}, clear=True):
                user_id = resoudre_utilisateur_actif()
                self.assertEqual(user_id, "osuser")

    def test_resoudre_utilisateur_actif_fallback_default(self):
        """Teste le fallback ultime vers 'default'."""
        with patch("context_engine.user_profile.getpass.getuser", side_effect=Exception):
            with patch("context_engine.user_profile.os.getlogin", side_effect=Exception):
                with patch.dict(os.environ, {}, clear=True):
                    user_id = resoudre_utilisateur_actif()
                    self.assertEqual(user_id, "default")

    def test_profil_par_defaut_structure(self):
        """Teste que le profil par défaut a la structure attendue."""
        profil = _profil_par_defaut("testuser")
        
        self.assertEqual(profil["user_id"], "testuser")
        self.assertEqual(profil["nom"], "Testuser")
        self.assertEqual(profil["role"], "utilisateur")
        self.assertEqual(profil["langue"], "français")
        self.assertIn("style_cognitif", profil)
        self.assertIn("rythme_activite", profil)
        self.assertIn("directives_personnelles", profil)
        
        # Vérifier les sous-structures
        self.assertEqual(profil["style_cognitif"]["format_prefere"], "synthese")
        self.assertTrue(profil["style_cognitif"]["concis"])
        self.assertEqual(profil["style_cognitif"]["niveau_technique"], 0.5)
        
        self.assertEqual(profil["rythme_activite"]["derniere_session"], "")
        self.assertEqual(profil["rythme_activite"]["nombre_interactions"], 0)
        self.assertEqual(profil["rythme_activite"]["creneaux_heures"], [])

    def test_charger_profil_nouveau_utilisateur(self):
        """Teste la création automatique d'un profil pour un nouvel utilisateur."""
        profil = charger_profil("alice")
        
        self.assertEqual(profil["user_id"], "alice")
        self.assertEqual(profil["nom"], "Alice")
        self.assertEqual(profil["role"], "utilisateur")
        
        # Vérifier que le fichier a été créé
        chemin = _chemin_profil("alice")
        self.assertTrue(chemin.exists())
        
        # Vérifier que le fichier contient les bonnes données
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["user_id"], "alice")

    def test_charger_profil_existant(self):
        """Teste le chargement d'un profil existant."""
        # Créer un profil personnalisé
        profil_personnalise = {
            "user_id": "bob",
            "nom": "Bob",
            "role": "developpeur",
            "langue": "english",
            "style_cognitif": {
                "format_prefere": "detaille",
                "concis": False,
                "niveau_technique": 0.8,
            },
            "rythme_activite": {
                "derniere_session": "2026-01-01 10:00:00",
                "nombre_interactions": 42,
                "creneaux_heures": [9, 10, 14, 15],
            },
            "directives_personnelles": {},
        }
        
        sauvegarder_profil(profil_personnalise, "bob")
        
        # Recharger et vérifier
        profil = charger_profil("bob")
        
        self.assertEqual(profil["nom"], "Bob")
        self.assertEqual(profil["role"], "developpeur")
        self.assertEqual(profil["langue"], "english")
        self.assertEqual(profil["style_cognitif"]["format_prefere"], "detaille")
        self.assertEqual(profil["rythme_activite"]["nombre_interactions"], 42)

    def test_sauvegarder_profil(self):
        """Teste la sauvegarde d'un profil."""
        profil = {
            "user_id": "charlie",
            "nom": "Charlie",
            "role": "visiteur",
            "langue": "français",
            "style_cognitif": {
                "format_prefere": "technique",
                "concis": True,
                "niveau_technique": 0.9,
            },
            "rythme_activite": {
                "derniere_session": "",
                "nombre_interactions": 0,
                "creneaux_heures": [],
            },
            "directives_personnelles": {},
        }
        
        sauvegarder_profil(profil, "charlie")
        
        # Vérifier que le fichier existe
        chemin = _chemin_profil("charlie")
        self.assertTrue(chemin.exists())
        
        # Vérifier le contenu
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["nom"], "Charlie")
            self.assertEqual(data["role"], "visiteur")
            # Vérifier que la dernière session a été mise à jour
            self.assertNotEqual(data["rythme_activite"]["derniere_session"], "")

    def test_sauvegarder_profil_met_a_jour_derniere_session(self):
        """Teste que sauvegarder_profil met à jour la dernière session."""
        profil = charger_profil("diane")
        
        # Sauvegarder
        sauvegarder_profil(profil, "diane")
        
        # Recharger et vérifier que la session a été mise à jour
        profil = charger_profil("diane")
        session = profil["rythme_activite"]["derniere_session"]
        
        # Vérifier que la session n'est plus vide
        self.assertNotEqual(session, "")
        # Vérifier le format du timestamp
        self.assertRegex(session, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_mettre_a_jour_directive_profil(self):
        """Teste l'ajout d'une directive personnelle."""
        mettre_a_jour_directive_profil("test_key", "Je préfère les réponses courtes", "eve")
        
        profil = charger_profil("eve")
        
        self.assertIn("test_key", profil["directives_personnelles"])
        self.assertEqual(profil["directives_personnelles"]["test_key"], "Je préfère les réponses courtes")
        
        # Vérifier que le compteur d'interactions a été incrémenté
        self.assertEqual(profil["rythme_activite"]["nombre_interactions"], 1)

    def test_mettre_a_jour_directive_profil_multiple(self):
        """Teste l'ajout de plusieurs directives."""
        mettre_a_jour_directive_profil("key1", "Directive 1", "frank")
        mettre_a_jour_directive_profil("key2", "Directive 2", "frank")
        mettre_a_jour_directive_profil("key3", "Directive 3", "frank")
        
        profil = charger_profil("frank")
        
        self.assertEqual(len(profil["directives_personnelles"]), 3)
        self.assertEqual(profil["directives_personnelles"]["key1"], "Directive 1")
        self.assertEqual(profil["directives_personnelles"]["key2"], "Directive 2")
        self.assertEqual(profil["directives_personnelles"]["key3"], "Directive 3")
        
        # Vérifier que le compteur a été incrémenté 3 fois
        self.assertEqual(profil["rythme_activite"]["nombre_interactions"], 3)

    def test_obtenir_contexte_profil_compact(self):
        """Teste la génération du contexte compact pour le prompt."""
        # Créer un profil avec des directives
        mettre_a_jour_directive_profil("dir1", "Utilise toujours le français", "grace")
        mettre_a_jour_directive_profil("dir2", "Sois concis", "grace")
        
        contexte = obtenir_contexte_profil_compact("grace")
        
        self.assertIn("Profil Utilisateur Actif", contexte)
        self.assertIn("Grace", contexte)
        self.assertIn("rôle : utilisateur", contexte)
        self.assertIn("Préférence de réponse", contexte)
        self.assertIn("Directives personnelles en vigueur", contexte)
        self.assertIn("Utilise toujours le français", contexte)
        self.assertIn("Sois concis", contexte)

    def test_obtenir_contexte_profil_compact_sans_directives(self):
        """Teste le contexte compact sans directives personnelles."""
        contexte = obtenir_contexte_profil_compact("henry")
        
        self.assertIn("Profil Utilisateur Actif", contexte)
        self.assertIn("Directives personnelles en vigueur : aucune", contexte)

    def test_isolation_stricte_profils(self):
        """Teste qu'une directive pour alice n'apparaît pas dans le profil de bob."""
        # Ajouter une directive pour alice
        mettre_a_jour_directive_profil("alice_key", "Alice aime le bleu", "alice")
        
        # Ajouter une directive pour bob
        mettre_a_jour_directive_profil("bob_key", "Bob aime le rouge", "bob")
        
        # Vérifier l'isolation
        profil_alice = charger_profil("alice")
        profil_bob = charger_profil("bob")
        
        self.assertIn("alice_key", profil_alice["directives_personnelles"])
        self.assertNotIn("bob_key", profil_alice["directives_personnelles"])
        
        self.assertIn("bob_key", profil_bob["directives_personnelles"])
        self.assertNotIn("alice_key", profil_bob["directives_personnelles"])

    def test_isolation_stricte_fichiers(self):
        """Teste que les fichiers de profil sont isolés sur disque."""
        charger_profil("isaac")
        charger_profil("julia")
        
        chemin_isaac = _chemin_profil("isaac")
        chemin_julia = _chemin_profil("julia")
        
        self.assertTrue(chemin_isaac.exists())
        self.assertTrue(chemin_julia.exists())
        self.assertNotEqual(chemin_isaac, chemin_julia)
        
        # Vérifier qu'ils sont dans des sous-dossiers différents
        self.assertNotEqual(chemin_isaac.parent, chemin_julia.parent)

    def test_charger_profil_sans_user_id_resolution_dynamique(self):
        """Teste le chargement sans user_id explicite (résolution dynamique)."""
        with patch.dict(os.environ, {"GREATOS_USER": "envuser"}):
            profil = charger_profil()
            self.assertEqual(profil["user_id"], "envuser")

    def test_sauvegarder_profil_sans_user_id_resolution_dynamique(self):
        """Teste la sauvegarde sans user_id explicite (résolution dynamique)."""
        with patch.dict(os.environ, {"GREATOS_USER": "envuser2"}):
            profil = charger_profil()
            sauvegarder_profil(profil)
            
            # Vérifier que le fichier a été créé avec le bon user_id
            chemin = _chemin_profil("envuser2")
            self.assertTrue(chemin.exists())

    def test_mettre_a_jour_directive_sans_user_id(self):
        """Teste la mise à jour de directive sans user_id explicite."""
        with patch.dict(os.environ, {"GREATOS_USER": "envuser3"}):
            mettre_a_jour_directive_profil("key", "Directive test")
            
            profil = charger_profil("envuser3")
            self.assertIn("key", profil["directives_personnelles"])

    def test_obtenir_contexte_sans_user_id(self):
        """Teste l'obtention du contexte sans user_id explicite."""
        with patch.dict(os.environ, {"GREATOS_USER": "envuser4"}):
            contexte = obtenir_contexte_profil_compact()
            self.assertIn("Envuser4", contexte)

    def test_fichier_profil_corrompu_recree(self):
        """Teste qu'un fichier corrompu entraîne la recréation du profil."""
        # Créer un fichier corrompu
        chemin = _chemin_profil("karen")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("{invalid json content")
        
        # Charger devrait recréer le profil
        profil = charger_profil("karen")
        
        self.assertEqual(profil["user_id"], "karen")
        self.assertEqual(profil["nom"], "Karen")
        self.assertEqual(profil["role"], "utilisateur")

    def test_user_id_force_dans_sauvegarde(self):
        """Teste que le user_id est forcé lors de la sauvegarde."""
        profil = {
            "user_id": "wrong_id",
            "nom": "Leo",
            "role": "utilisateur",
            "langue": "français",
            "style_cognitif": {
                "format_prefere": "synthese",
                "concis": True,
                "niveau_technique": 0.5,
            },
            "rythme_activite": {
                "derniere_session": "",
                "nombre_interactions": 0,
                "creneaux_heures": [],
            },
            "directives_personnelles": {},
        }
        
        sauvegarder_profil(profil, "leo")
        
        # Recharger et vérifier que le user_id a été corrigé
        profil = charger_profil("leo")
        self.assertEqual(profil["user_id"], "leo")


if __name__ == "__main__":
    unittest.main()
