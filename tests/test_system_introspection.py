"""Tests de validation de l'introspection déterministe de GreatOS pour Jarvis."""

import unittest
from core_intellect.system_introspection import (
    consulter_etat_maison,
    inspecter_architecture_greatos,
    consulter_historique_projet,
)
from core_intellect.intent_router import router_intention, IntentCategory


class TestSystemIntrospection(unittest.TestCase):
    def test_consulter_etat_maison(self):
        etat = consulter_etat_maison()
        self.assertIsInstance(etat, dict)
        self.assertIn("contexte_os", etat)
        self.assertIn("layout_morphique", etat)
        self.assertIn("systeme", etat)
        self.assertIn("securite", etat)

    def test_inspecter_architecture_greatos(self):
        # Tous les modules
        archi = inspecter_architecture_greatos()
        self.assertIn("core_intellect", archi)
        self.assertIn("datashield", archi)
        self.assertIn("taskflow", archi)
        self.assertIn("interface_morphique", archi)

        # Un module spécifique
        mod = inspecter_architecture_greatos("datashield")
        self.assertEqual(len(mod), 1)
        self.assertIn("fichiers_cles", mod["datashield"])

    def test_consulter_historique_projet(self):
        historique = consulter_historique_projet(nombre=2)
        self.assertIsInstance(historique, list)
        if historique:
            premier = historique[0]
            self.assertIn("timestamp", premier)
            self.assertIn("agent", premier)
            self.assertIn("resume", premier)

    def test_routage_deterministe_introspection(self):
        route_maison = router_intention("Quel est l'état de la maison ?")
        self.assertEqual(route_maison.category, IntentCategory.DIAGNOSTIC)
        self.assertTrue(route_maison.needs_tool_signatures)

        route_archi = router_intention("Montre-moi l'architecture de GreatOS")
        self.assertEqual(route_archi.category, IntentCategory.DIAGNOSTIC)

        route_hist = router_intention("Historique du projet s'il te plaît")
        self.assertEqual(route_hist.category, IntentCategory.DIAGNOSTIC)


if __name__ == "__main__":
    unittest.main()
