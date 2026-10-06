"""Tests unitaires pour interface_morphique/context_switcher.py."""

import unittest
from interface_morphique.context_switcher import (
    MorphicContextEngine,
    MorphicLayout,
    get_morphic_engine,
)


class TestMorphicContextSwitcher(unittest.TestCase):
    def setUp(self):
        self.engine = MorphicContextEngine()

    def test_default_layout_is_chat(self):
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.CHAT)

    def test_transition_to_focus_on_ide_or_fullscreen(self):
        # Simulation d'un événement OS hook fenêtrage IDE
        self.engine.notifier_evenement("os_context_changed", {
            "application": "Visual Studio Code",
            "processus": "Code.exe",
            "plein_ecran": False,
        })
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.FOCUS)

        # Simulation d'un événement retour au bureau
        self.engine.notifier_evenement("os_context_changed", {
            "application": "Explorateur Windows",
            "processus": "explorer.exe",
            "plein_ecran": False,
        })
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.CHAT)

    def test_transition_to_vocal_hud(self):
        self.engine.notifier_evenement("vocal_state_changed", {"state": "listening"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.VOCAL_HUD)

        self.engine.notifier_evenement("vocal_state_changed", {"state": "idle"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.CHAT)

    def test_transition_to_task_runner(self):
        self.engine.notifier_evenement("stark_activated", {"objectif": "Deploy"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.TASK_RUNNER)

        self.engine.notifier_evenement("stark_desactive", {})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.CHAT)

    def test_transition_to_web_nav(self):
        self.engine.notifier_evenement("browser_session", {"state": "navigating"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.WEB_NAV)

        self.engine.notifier_evenement("browser_session", {"state": "closed"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.CHAT)

    def test_transition_to_defcon_alert_priority(self):
        # Même si vocal actif, alerte sécurité l'emporte
        self.engine.notifier_evenement("vocal_state_changed", {"state": "listening"})
        self.engine.notifier_evenement("alerte_proactive", {"type": "defcon_critical"})
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.DEFCON_ALERT)

        self.engine.notifier_evenement("alerte_proactive_resolue", {"type": "defcon_critical"})
        # Redevient vocal car encore actif
        self.assertEqual(self.engine.get_current_layout(), MorphicLayout.VOCAL_HUD)

    def test_callback_notification(self):
        transitions = []

        def on_change(layout, payload):
            transitions.append((layout, payload["nouveau_layout"]))

        self.engine.abonner_changement_layout(on_change)
        self.engine.notifier_evenement("stark_activated", {})
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0][0], MorphicLayout.TASK_RUNNER)


if __name__ == "__main__":
    unittest.main()
