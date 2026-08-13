import unittest

import jarvis


class InteractionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.original_executer_agent = jarvis.executer_agent
        self.original_journal = jarvis.OUTILS["enregistrer_echange"]
        self.calls = []

        def fake_executer_agent(message, historique, memoire):
            self.calls.append(("execute", message, historique, memoire))
            return "Réponse exécutée", True

        def fake_journal(message, reponse):
            self.calls.append(("journal", message, reponse))

        jarvis.executer_agent = fake_executer_agent
        jarvis.OUTILS["enregistrer_echange"] = fake_journal

    def tearDown(self):
        jarvis.executer_agent = self.original_executer_agent
        jarvis.OUTILS["enregistrer_echange"] = self.original_journal

    def test_common_pipeline_prepares_executes_and_journals(self):
        historique = []
        memoire = {}

        reponse, intention_action = jarvis.executer_interaction_utilisateur(
            "  bonjour  ", historique, memoire
        )

        self.assertEqual((reponse, intention_action), ("Réponse exécutée", True))
        self.assertEqual(self.calls[0], ("execute", "bonjour", historique, memoire))
        self.assertEqual(self.calls[1], ("journal", "bonjour", "Réponse exécutée"))

    def test_common_pipeline_applies_optimization_context_before_execution(self):
        historique = []

        jarvis.executer_interaction_utilisateur("optimise le PC", historique, {})

        prepared_message = self.calls[0][1]
        self.assertTrue(prepared_message.startswith("optimise le PC"))
        self.assertIn(jarvis.PLAN_OPTIMISATION, prepared_message)

    def test_voice_can_skip_when_another_surface_owns_pipeline_lock(self):
        self.assertTrue(jarvis.INTERACTION_LOCK.acquire(blocking=False))
        try:
            result = jarvis.executer_interaction_utilisateur(
                "bonjour", [], {}, ignorer_si_occupe=True
            )
        finally:
            jarvis.INTERACTION_LOCK.release()

        self.assertIsNone(result)
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
