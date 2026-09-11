# tests/test_greatos_modules.py
"""Tests unitaires pour les modules fondamentaux du Kernel GreatOS."""

import unittest
import tempfile
from pathlib import Path
import json

from greatos import GreatOSKernel
from datashield.defcon import DefconManager, DefconLevel
from progress_tracker.goals import GoalManager, GoalType, GoalStatus
from progress_tracker.analytics import calculer_statistiques_globales
from syncsphere.snapshot import SnapshotManager
from taskflow.tools import (
    obtenir_niveau_defcon,
    changer_niveau_defcon,
    creer_objectif_tool,
    lister_objectifs_tool,
    mettre_a_jour_objectif_tool,
    stats_objectifs_tool,
    creer_snapshot_systeme_tool,
    lister_snapshots_systeme_tool,
    OUTILS,
)


class TestGreatOSKernel(unittest.TestCase):
    """Vérifie le fonctionnement du noyau central GreatOS."""

    def setUp(self):
        self.kernel = GreatOSKernel()

    def test_kernel_initialisation(self):
        self.assertIn("GreatOS", self.kernel.version)
        self.assertIsNotNone(self.kernel.defcon)
        self.assertIsNotNone(self.kernel.goals)
        self.assertIsNotNone(self.kernel.sync)

    def test_rapport_etat(self):
        rapport = self.kernel.rapport_etat()
        self.assertEqual(rapport["os"], "GreatOS")
        self.assertIn("defcon", rapport)
        self.assertIn("systeme", rapport)
        self.assertIn("version", rapport)


class TestDataShieldDefcon(unittest.TestCase):
    """Vérifie la gestion des états DEFCON et les restrictions associées."""

    def setUp(self):
        self.manager = DefconManager(default_level=DefconLevel.DEFCON_5)

    def test_transitions_defcon(self):
        self.assertEqual(self.manager.current_level, DefconLevel.DEFCON_5)
        self.manager.set_level(DefconLevel.DEFCON_3)
        self.assertEqual(self.manager.current_level, DefconLevel.DEFCON_3)

    def test_listener_notification(self):
        transitions = []
        def on_change(old, new):
            transitions.append((old, new))

        self.manager.add_listener(on_change)
        self.manager.set_level(DefconLevel.DEFCON_2)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (DefconLevel.DEFCON_5, DefconLevel.DEFCON_2))

    def test_permissions_defcon(self):
        # DEFCON 5: tout est permis
        self.manager.set_level(DefconLevel.DEFCON_5)
        self.assertTrue(self.manager.is_action_allowed(is_destructive=True, is_system_call=True))

        # DEFCON 3: commandes système bloquées
        self.manager.set_level(DefconLevel.DEFCON_3)
        self.assertFalse(self.manager.is_action_allowed(is_destructive=False, is_system_call=True))
        self.assertTrue(self.manager.is_action_allowed(is_destructive=False, is_system_call=False))

        # DEFCON 2: actions destructives bloquées
        self.manager.set_level(DefconLevel.DEFCON_2)
        self.assertFalse(self.manager.is_action_allowed(is_destructive=True, is_system_call=False))

        # DEFCON 1: confinement total
        self.manager.set_level(DefconLevel.DEFCON_1)
        self.assertFalse(self.manager.is_action_allowed(is_destructive=False, is_system_call=False))


class TestProgressTracker(unittest.TestCase):
    """Vérifie le cycle de vie des objectifs et métriques de progression."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.goals_file = Path(self.tmp_dir.name) / "goals.json"
        self.manager = GoalManager(storage_path=self.goals_file)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_creation_et_progression_objectif(self):
        g = self.manager.creer_objectif("obj_1", "Tester GreatOS", cible=100.0, unite="%")
        self.assertEqual(g.id, "obj_1")
        self.assertEqual(g.status, GoalStatus.ACTIVE)
        self.assertEqual(g.progression_pourcentage, 0.0)

        # Mise à jour progression
        g_maj = self.manager.mettre_a_jour_progression("obj_1", 50.0)
        self.assertEqual(g_maj.valeur_actuelle, 50.0)
        self.assertEqual(g_maj.progression_pourcentage, 50.0)

        # Complétion
        g_done = self.manager.mettre_a_jour_progression("obj_1", 100.0)
        self.assertEqual(g_done.status, GoalStatus.COMPLETED)


class TestSyncSphereSnapshot(unittest.TestCase):
    """Vérifie la création et la cohérence des snapshots locaux .gos."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmp_dir.name)
        # Créer un faux memory.json
        (self.root_path / "memory.json").write_text(json.dumps({"test": True}))
        self.snapshot_mgr = SnapshotManager(root_dir=self.root_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_creer_et_lister_snapshot(self):
        archive = self.snapshot_mgr.creer_snapshot(nom="test_snapshot.gos")
        self.assertTrue(archive.exists())
        self.assertTrue(archive.name.endswith(".gos"))

        liste = self.snapshot_mgr.lister_snapshots()
        self.assertEqual(len(liste), 1)
        self.assertEqual(liste[0]["nom"], "test_snapshot.gos")


class TestGreatOSToolsRegistration(unittest.TestCase):
    """Vérifie que les nouveaux outils GreatOS sont bien enregistrés dans OUTILS."""

    def test_outils_presents(self):
        outils_attendus = [
            "obtenir_niveau_defcon",
            "changer_niveau_defcon",
            "creer_objectif",
            "lister_objectifs",
            "mettre_a_jour_objectif",
            "stats_objectifs",
            "creer_snapshot_systeme",
            "lister_snapshots_systeme",
        ]
        for outil in outils_attendus:
            self.assertIn(outil, OUTILS, f"Outil manquant: {outil}")

    def test_execution_outils_defcon(self):
        rep = obtenir_niveau_defcon()
        self.assertIn("DEFCON", rep)

        rep_chg = changer_niveau_defcon(4)
        self.assertIn("DEFCON_4", rep_chg)
        changer_niveau_defcon(5)  # Restauration
