"""Tests d'intégration des 8 Modules du Cahier des Charges GreatOS."""

import unittest

# 1. Jarvis
from core_intellect.intent_router import router_intention, IntentCategory

# 2. Core Intellect
from core_intellect.multi_criteria_decision import evaluer_decision, arbitrer_priorite_taches, PrioriteNiveau

# 3. Context Engine
from context_engine.four_dimensions import capturer_contexte_quadridimensionnel, ContexteQuadridimensionnel

# 4. TaskFlow
from taskflow.preconfigured_workflows import lister_workflows_preconfigures, executer_workflow_preconfigure

# 5. Progress Tracker
from progress_tracker.gamification import attribuer_xp, charger_etat_gamification

# 6. DataShield
from datashield.policy import evaluate_capability
from greatos_contracts import CapabilityRequest, RiskLevel, SecurityDecision

# 7. SyncSphere
from syncsphere.tools import lister_snapshots_systeme_tool

# 8. Interface Morphique
from interface_morphique.context_switcher import get_morphic_engine, MorphicLayout


class TestEightModulesCDC(unittest.TestCase):
    def test_module_1_jarvis_intent_routing(self):
        """Module 1 : Jarvis écoute et route l'intention de dialogue."""
        route = router_intention("Bonjour Jarvis, comment vas-tu ?")
        self.assertEqual(route.category, IntentCategory.CONVERSATION)
        self.assertFalse(route.needs_tool_signatures)

    def test_module_2_core_intellect_decision(self):
        """Module 2 : Core Intellect arbitre selon l'urgence, l'importance et l'effort."""
        ev = evaluer_decision(nom="Tâche urgente critique", urgence=5, importance=5, effort=1)
        self.assertGreaterEqual(ev.score_decision, 3.8)
        self.assertEqual(ev.priorite, PrioriteNiveau.CRITIQUE)

    def test_module_3_context_engine_four_dimensions(self):
        """Module 3 : Context Engine capture les 4 dimensions (temporelle, cognitive, opérationnelle, spatiale)."""
        ctx = capturer_contexte_quadridimensionnel()
        self.assertIsInstance(ctx, ContexteQuadridimensionnel)
        self.assertIsNotNone(ctx.temporel.phase)
        self.assertIsNotNone(ctx.cognitif.charge)
        self.assertIsNotNone(ctx.operationnel.application)
        self.assertIsNotNone(ctx.spatial.hote)

    def test_module_4_taskflow_preconfigured_workflows(self):
        """Module 4 : TaskFlow dispose de workflows préconfigurés."""
        catalogue = lister_workflows_preconfigures()
        self.assertIn("session_dev", catalogue)
        self.assertIn("nettoyage_systeme", catalogue)
        res = executer_workflow_preconfigure("session_dev")
        self.assertTrue(res["succes"])
        self.assertGreater(len(res["etapes"]), 0)

    def test_module_5_progress_tracker_gamification(self):
        """Module 5 : Progress Tracker gère les points d'XP et les niveaux."""
        res = attribuer_xp(50, raison="Test unitaire CDC")
        self.assertGreaterEqual(res["total_xp"], 50)
        self.assertIn("titre_rang", res)

    def test_module_6_datashield_policy_evaluation(self):
        """Module 6 : DataShield évalue la sécurité et bloque les sources externes destructrices."""
        from greatos_contracts import RequestOrigin
        req = CapabilityRequest(
            capability="system.delete_all",
            risk=RiskLevel.DESTRUCTIVE,
            origin=RequestOrigin.EXTERNAL,
        )
        decision = evaluate_capability(req)
        self.assertEqual(decision.decision, SecurityDecision.DENY)

    def test_module_7_syncsphere_local_snapshots(self):
        """Module 7 : SyncSphere gère les snapshots locaux souverains."""
        res = lister_snapshots_systeme_tool()
        self.assertIsInstance(res, str)

    def test_module_8_interface_morphique_layout(self):
        """Module 8 : Interface Morphique gère les layouts adaptatifs."""
        engine = get_morphic_engine()
        layout = engine.get_current_layout()
        self.assertIn(layout, list(MorphicLayout))


if __name__ == "__main__":
    unittest.main()
