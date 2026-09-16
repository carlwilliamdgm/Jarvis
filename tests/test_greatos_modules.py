# tests/test_greatos_modules.py
"""Tests unitaires pour les modules fondamentaux du Kernel GreatOS."""

import unittest
import tempfile
from pathlib import Path
import json

from greatos import GreatOSKernel
from datashield.defcon import DefconManager, DefconLevel
from progress_tracker.goals import GoalManager, GoalType, GoalStatus, goal_manager, enregistrer_impact_capacite
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
from greatos_capabilities import execute_capability, list_capabilities, resolve_capability
from greatos_contracts import CapabilityResult, CapabilityStatus, PolicyDecision, SecurityDecision
from context_engine.memory import (
    charger_memoire,
    consulter_trace_capacites,
    filtrer_arguments_sensibles,
    journaliser_resultat_capacite,
    sauvegarder_memoire,
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


class TestSovereignModuleTools(unittest.TestCase):
    """Vérifie la migration de propriété des capacités vers les modules souverains (Étape 4)."""

    def test_datashield_exports_and_identity(self):
        import datashield
        import datashield.tools as ds_tools
        self.assertTrue(callable(datashield.obtenir_niveau_defcon))
        self.assertTrue(callable(datashield.changer_niveau_defcon))
        self.assertIs(OUTILS["obtenir_niveau_defcon"], ds_tools.obtenir_niveau_defcon)
        self.assertIs(OUTILS["changer_niveau_defcon"], ds_tools.changer_niveau_defcon)

    def test_progress_tracker_exports_and_identity(self):
        import progress_tracker
        import progress_tracker.tools as pt_tools
        self.assertTrue(callable(progress_tracker.creer_objectif_tool))
        self.assertTrue(callable(progress_tracker.lister_objectifs_tool))
        self.assertTrue(callable(progress_tracker.mettre_a_jour_objectif_tool))
        self.assertTrue(callable(progress_tracker.stats_objectifs_tool))
        self.assertIs(OUTILS["creer_objectif"], pt_tools.creer_objectif_tool)
        self.assertIs(OUTILS["lister_objectifs"], pt_tools.lister_objectifs_tool)
        self.assertIs(OUTILS["mettre_a_jour_objectif"], pt_tools.mettre_a_jour_objectif_tool)
        self.assertIs(OUTILS["stats_objectifs"], pt_tools.stats_objectifs_tool)

    def test_syncsphere_exports_and_identity(self):
        import syncsphere
        import syncsphere.tools as ss_tools
        self.assertTrue(callable(syncsphere.creer_snapshot_systeme_tool))
        self.assertTrue(callable(syncsphere.lister_snapshots_systeme_tool))
        self.assertIs(OUTILS["creer_snapshot_systeme"], ss_tools.creer_snapshot_systeme_tool)
        self.assertIs(OUTILS["lister_snapshots_systeme"], ss_tools.lister_snapshots_systeme_tool)

    def test_interface_morphique_exports_and_identity(self):
        import interface_morphique
        import interface_morphique.tools as im_tools
        self.assertTrue(callable(interface_morphique.demarrer_overlay_navigation))
        self.assertTrue(callable(interface_morphique.arreter_overlay_navigation))
        self.assertIs(OUTILS["demarrer_overlay_navigation"], im_tools.demarrer_overlay_navigation)
        self.assertIs(OUTILS["arreter_overlay_navigation"], im_tools.arreter_overlay_navigation)

    def test_context_engine_exports_and_identity(self):
        import context_engine
        import context_engine.memory_tools as ce_tools
        self.assertTrue(callable(context_engine.lire_traces_capacites))
        self.assertTrue(callable(context_engine.lire_journal_agents))
        self.assertIs(OUTILS["lire_traces_capacites"], ce_tools.lire_traces_capacites)
        self.assertIs(OUTILS["lire_journal_agents"], ce_tools.lire_journal_agents)


class TestCapabilityOwnership(unittest.TestCase):
    """La façade historique doit exposer une propriété de module explicite."""

    def test_every_legacy_tool_has_one_owner(self):
        capabilities = list_capabilities(OUTILS)
        self.assertEqual(len(capabilities), len(OUTILS))
        self.assertTrue(all(capability.owner for capability in capabilities))

    def test_canonical_and_legacy_names_resolve_to_same_capability(self):
        canonical = resolve_capability(OUTILS, "system.execute_command")
        legacy = resolve_capability(OUTILS, "executer_commande")
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical, legacy)
        self.assertEqual(canonical.owner, "taskflow")

    def test_dispatcher_returns_a_structured_result_for_alias_and_canonical_name(self):
        registry = {"echo": lambda value: value}
        result = execute_capability(registry, "echo", {"value": "ok"})
        self.assertEqual(result.status, CapabilityStatus.SUCCESS)
        self.assertEqual(result.message, "ok")
        self.assertEqual(result.data["legacy_tool"], "echo")


class TestCapabilityTraceability(unittest.TestCase):
    """Vérifie la traçabilité des CapabilityResult dans Context Engine (Étape 2)."""

    def setUp(self):
        self.backup = charger_memoire()
        sauvegarder_memoire({})

    def tearDown(self):
        sauvegarder_memoire(self.backup)

    def test_journaliser_resultat_capacite_records_metadata_and_duration(self):
        result = CapabilityResult(
            capability="filesystem.read",
            status=CapabilityStatus.SUCCESS,
            message="Contenu du fichier lu avec succès.",
            data={"owner": "taskflow", "legacy_tool": "lire_fichier", "duration_ms": 12.5},
        )
        decision = PolicyDecision(decision=SecurityDecision.ALLOW, reason="Lecture autorisée")
        entry = journaliser_resultat_capacite(
            result,
            arguments={"chemin": "C:/dossier/test.txt"},
            decision=decision,
            contexte="test_trace",
        )
        self.assertEqual(entry["capability"], "filesystem.read")
        self.assertEqual(entry["owner"], "taskflow")
        self.assertEqual(entry["status"], "success")
        self.assertEqual(entry["decision"]["decision"], "allow")
        self.assertEqual(entry["duree_ms"], 12.5)
        self.assertEqual(entry["contexte"], "test_trace")

        # Vérifier la présence dans l'historique
        traces = consulter_trace_capacites(limite=5)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["capability"], "filesystem.read")

    def test_filtering_sensitive_arguments_and_secrets(self):
        # Clés sensibles masquées
        args = {
            "api_key": "sk-proj-1234567890abcdef",
            "password": "super_secret_password",
            "token": "ghp_111222333444555666777888999000111222",
            "Authorization": "Bearer secret_jwt_token_here",
            "normal_arg": "valeur_normale",
        }
        filtered = filtrer_arguments_sensibles(args)
        self.assertEqual(filtered["api_key"], "[MASQUÉ]")
        self.assertEqual(filtered["password"], "[MASQUÉ]")
        self.assertEqual(filtered["token"], "[MASQUÉ]")
        self.assertEqual(filtered["Authorization"], "[MASQUÉ]")
        self.assertEqual(filtered["normal_arg"], "valeur_normale")

        # Chaîne contenant un token sensible masquée
        res = CapabilityResult(
            capability="web.search",
            status=CapabilityStatus.SUCCESS,
            message="Résultat avec Authorization: Bearer abcdef123456 inclus",
            data={"owner": "taskflow", "legacy_tool": "rechercher_web", "duration_ms": 45.0},
        )
        entry = journaliser_resultat_capacite(res, arguments=args)
        self.assertNotIn("sk-proj", str(entry))
        self.assertNotIn("super_secret_password", str(entry))
        self.assertNotIn("abcdef123456", entry["resultat"])

    def test_consulter_trace_capacites_filtering(self):
        r1 = CapabilityResult(capability="goals.create", status=CapabilityStatus.SUCCESS, message="ok", data={"owner": "progress_tracker", "legacy_tool": "creer_objectif"})
        r2 = CapabilityResult(capability="system.execute_command", status=CapabilityStatus.DENIED, message="bloqué", data={"owner": "taskflow", "legacy_tool": "executer_commande"})
        r3 = CapabilityResult(capability="memory.note", status=CapabilityStatus.SUCCESS, message="noté", data={"owner": "context_engine", "legacy_tool": "noter"})

        journaliser_resultat_capacite(r1)
        journaliser_resultat_capacite(r2)
        journaliser_resultat_capacite(r3)

        by_owner = consulter_trace_capacites(proprietaire="context_engine")
        self.assertEqual(len(by_owner), 1)
        self.assertEqual(by_owner[0]["capability"], "memory.note")

        by_status = consulter_trace_capacites(statut="denied")
        self.assertEqual(len(by_status), 1)
        self.assertEqual(by_status[0]["capability"], "system.execute_command")

    def test_status_refinement_in_dispatcher(self):
        class FauxOutilRefusConfirmation:
            def __call__(self):
                class Res:
                    erreur = True
                    categorie_erreur = "action_refusee_par_confirmation"
                    def __str__(self):
                        return "Annulé par l'utilisateur."
                return Res()

        class FauxOutilDefconBlocked:
            def __call__(self):
                class Res:
                    erreur = True
                    categorie_erreur = "defcon_blocked"
                    def __str__(self):
                        return "Action bloquée par DEFCON 1."
                return Res()

        registry = {
            "cmd_annulee": FauxOutilRefusConfirmation(),
            "cmd_bloquee": FauxOutilDefconBlocked(),
        }
        res_cancel = execute_capability(registry, "cmd_annulee")
        self.assertEqual(res_cancel.status, CapabilityStatus.CANCELLED)

        res_deny = execute_capability(registry, "cmd_bloquee")
        self.assertEqual(res_deny.status, CapabilityStatus.DENIED)


class TestProgressTrackerCapabilityIntegration(unittest.TestCase):
    """Vérifie la mesure de progression souveraine dans Progress Tracker (Étape 3)."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.tmp_dir.name) / "test_goals.json"
        self.mgr = GoalManager(storage_path=self.storage_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_capability_impact_increments_linked_goal_when_successful(self):
        goal = self.mgr.creer_objectif(
            id_obj="obj_cmd",
            titre="Exécuter 10 commandes système",
            cible=10.0,
            unite="commandes",
        )
        self.assertEqual(goal.valeur_actuelle, 0.0)

        res = CapabilityResult(
            capability="system.execute_command",
            status=CapabilityStatus.SUCCESS,
            message="Commande terminée",
            data={"owner": "taskflow", "duration_ms": 40.0},
        )
        impact = self.mgr.enregistrer_impact_capacite(res, goal_id="obj_cmd", increment=1.0)
        self.assertEqual(impact["objectif_lie"], "obj_cmd")
        self.assertTrue(impact["progression_appliquee"])
        self.assertEqual(impact["progression_pourcentage"], 10.0)
        self.assertEqual(goal.valeur_actuelle, 1.0)

        metrics = self.mgr.obtenir_metriques_execution()
        self.assertEqual(metrics["total_actions"], 1)
        self.assertEqual(metrics["total_succes"], 1)
        self.assertEqual(metrics["duree_totale_ms"], 40.0)

    def test_no_progression_invented_when_no_goal_linked(self):
        goal = self.mgr.creer_objectif(
            id_obj="obj_other",
            titre="Rédiger un rapport",
            cible=1.0,
            unite="rapport",
        )
        res = CapabilityResult(
            capability="web.search",
            status=CapabilityStatus.SUCCESS,
            message="Résultats trouvés",
            data={"owner": "taskflow", "duration_ms": 50.0},
        )
        impact = self.mgr.enregistrer_impact_capacite(res)
        self.assertIsNone(impact["objectif_lie"])
        self.assertFalse(impact["progression_appliquee"])
        # La valeur de l'objectif ne doit en aucun cas être inventée/incrémentée
        self.assertEqual(goal.valeur_actuelle, 0.0)
        self.assertEqual(goal.progression_pourcentage, 0.0)

    def test_failed_or_denied_capability_does_not_advance_goal(self):
        goal = self.mgr.creer_objectif(
            id_obj="obj_secure",
            titre="Opérations autorisées",
            cible=5.0,
        )
        res_denied = CapabilityResult(
            capability="system.execute_command",
            status=CapabilityStatus.DENIED,
            message="Action bloquée par DEFCON 1",
            data={"owner": "taskflow", "duration_ms": 5.0},
        )
        impact = self.mgr.enregistrer_impact_capacite(res_denied, goal_id="obj_secure")
        self.assertEqual(impact["objectif_lie"], "obj_secure")
        self.assertFalse(impact["progression_appliquee"])
        self.assertEqual(goal.valeur_actuelle, 0.0)

        metrics = self.mgr.obtenir_metriques_execution()
        self.assertEqual(metrics["total_echecs"], 1)

    def test_capability_targeted_goal_auto_links(self):
        goal = self.mgr.creer_objectif(
            id_obj="obj_notes",
            titre="Prendre 3 notes",
            cible=3.0,
            capacite_cible="memory.note",
        )
        res = CapabilityResult(
            capability="memory.note",
            status=CapabilityStatus.SUCCESS,
            message="Note enregistrée",
            data={"owner": "context_engine", "duration_ms": 10.0},
        )
        impact = self.mgr.enregistrer_impact_capacite(res)
        self.assertEqual(impact["objectif_lie"], "obj_notes")
        self.assertTrue(impact["progression_appliquee"])
        self.assertEqual(goal.valeur_actuelle, 1.0)
