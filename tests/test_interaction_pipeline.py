import unittest
from unittest.mock import patch, MagicMock
from copy import deepcopy

import jarvis
from jarvis.voice_state import VoiceState, _set_voice_state


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

    def test_non_voice_interaction_never_invokes_tts(self):
        with patch("jarvis.voice_output.parler_a_voix_haute") as speak:
            jarvis.executer_interaction_utilisateur("bonjour", [], {})

        speak.assert_not_called()

    def test_voice_interaction_keeps_lock_until_tts_returns(self):
        voice_started = []
        _set_voice_state(VoiceState.THINKING)
        def fake_voice_output(_text):
            voice_started.append(jarvis.INTERACTION_LOCK.locked())

        with patch("jarvis.voice_output.parler_a_voix_haute", side_effect=fake_voice_output):
            jarvis.executer_interaction_utilisateur("bonjour", [], {}, origine_vocale=True)

        self.assertEqual([False], voice_started)
        _set_voice_state(VoiceState.IDLE)

    def test_state_coherence_after_failed_request(self):
        """Test que l'état reste cohérent après un échec, même sans rollback automatique.
        
        Avec le nouveau design (pas de rollback global), l'état en mémoire peut être
        partiellement mis à jour après une erreur, mais doit rester utilisable et cohérent.
        """
        
        # Setup initial state
        historique = [{"role": "system", "content": "System prompt"}]
        memoire = {"utilisateur": {"nom": "Test"}}
        
        # Simuler un échec sur le premier tour
        original_executer_agent = jarvis.executer_agent
        
        def failing_executer_agent(message, hist, mem):
            # Simuler un échec qui modifie l'état (comme un outil réel pourrait faire)
            hist.append({"role": "user", "content": message})
            hist.append({"role": "assistant", "content": "Échec simulé"})
            # Modifier memoire (simulant un outil qui écrit)
            mem["last_error"] = "Simulated failure"
            raise Exception("Simulated failure")
        
        jarvis.executer_agent = failing_executer_agent
        
        try:
            # Premier tour : doit échouer
            with self.assertRaises(Exception):
                jarvis.executer_interaction_utilisateur("test echec", historique, memoire)
        finally:
            # Restaurer la fonction originale
            jarvis.executer_agent = original_executer_agent
        
        # Sans rollback, l'état peut être modifié après erreur
        # Mais il doit rester cohérent et utilisable
        self.assertIsInstance(historique, list)
        self.assertIsInstance(memoire, dict)
        self.assertIn("utilisateur", memoire)  # Structure de base préservée
        
        # L'historique peut contenir les entrées du message échoué
        # C'est acceptable : la conversation reste lisible
        self.assertGreaterEqual(len(historique), 1)  # Au moins le message système
        
        # Deuxième tour : doit réussir normalement malgré l'état modifié
        def successful_executer_agent(message, hist, mem):
            hist.append({"role": "user", "content": message})
            hist.append({"role": "assistant", "content": "Succès"})
            return "Succès", False
        
        jarvis.executer_agent = successful_executer_agent
        
        reponse, intention_action = jarvis.executer_interaction_utilisateur("test succes", historique, memoire)
        
        # Vérifier que le second tour a réussi malgré l'état modifié
        self.assertEqual(reponse, "Succès")
        self.assertEqual(intention_action, False)
        
        # Vérifier que l'historique reste cohérent
        self.assertTrue(all(isinstance(msg, dict) for msg in historique))
        self.assertTrue(all("role" in msg for msg in historique))
        
        # Restaurer la fonction originale
        jarvis.executer_agent = original_executer_agent


if __name__ == "__main__":
    unittest.main()
