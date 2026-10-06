"""Tests d'intégration pour l'endpoint /jarvis/layout et le streaming morphique."""

import unittest
from fastapi.testclient import TestClient

from interface_morphique.server import app
from interface_morphique.context_switcher import MorphicLayout, get_morphic_engine


class TestMorphicAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_current_layout_api(self):
        response = self.client.get("/jarvis/layout")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("layout", data)
        self.assertIn("os_context", data)
        self.assertIn("timestamp", data)
        self.assertIn(data["layout"], [l.value for l in MorphicLayout])

    def test_layout_updates_reflect_in_api(self):
        engine = get_morphic_engine()
        # Simuler un déclencheur vocal
        engine.notifier_evenement("vocal_state_changed", {"state": "listening"})
        response = self.client.get("/jarvis/layout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["layout"], MorphicLayout.VOCAL_HUD.value)

        # Réinitialiser
        engine.notifier_evenement("vocal_state_changed", {"state": "idle"})
        response = self.client.get("/jarvis/layout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["layout"], MorphicLayout.CHAT.value)


if __name__ == "__main__":
    unittest.main()
