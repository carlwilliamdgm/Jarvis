"""Tests de validation de l'authentification des appareils de confiance (Localhost & Tailscale)."""

import os
import unittest
from fastapi.testclient import TestClient

from interface_morphique.server import app, est_adresse_de_confiance


class TestTrustedDevicesAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.original_key = os.environ.get("JARVIS_API_KEY")
        os.environ["JARVIS_API_KEY"] = "super_secret_test_token_12345"

    def tearDown(self):
        if self.original_key is not None:
            os.environ["JARVIS_API_KEY"] = self.original_key
        else:
            os.environ.pop("JARVIS_API_KEY", None)

    def test_est_adresse_de_confiance_detection(self):
        # Localhost
        self.assertTrue(est_adresse_de_confiance("127.0.0.1"))
        self.assertTrue(est_adresse_de_confiance("::1"))
        self.assertTrue(est_adresse_de_confiance("localhost"))
        self.assertTrue(est_adresse_de_confiance("testclient"))

        # Tailscale IPv4 (100.64.0.0/10)
        self.assertTrue(est_adresse_de_confiance("100.64.0.1"))
        self.assertTrue(est_adresse_de_confiance("100.100.42.15"))
        self.assertTrue(est_adresse_de_confiance("100.127.255.254"))

        # Tailscale IPv6
        self.assertTrue(est_adresse_de_confiance("fd7a:115c:a1e0::1"))

        # IPs non autorisées (Internet public ou LAN classique)
        self.assertFalse(est_adresse_de_confiance("192.168.1.50"))
        self.assertFalse(est_adresse_de_confiance("8.8.8.8"))
        self.assertFalse(est_adresse_de_confiance("203.0.113.19"))
        self.assertFalse(est_adresse_de_confiance(None))

    def test_localhost_access_without_bearer_token(self):
        """Sur localhost (ou testclient), l'accès direct est autorisé sans clé."""
        resp = self.client.get("/jarvis/layout")
        self.assertEqual(resp.status_code, 200)

    def test_tailscale_ip_access_without_bearer_token(self):
        """Une requête provenant du Tailnet Tailscale est reconnue comme appareil de confiance."""
        # TestClient simule l'IP client via l'argument client=("IP", port)
        client_tailscale = TestClient(app, client=("100.90.80.70", 4242))
        resp = client_tailscale.get("/jarvis/layout")
        self.assertEqual(resp.status_code, 200)

    def test_untrusted_ip_blocked_without_token(self):
        """Une IP externe non approuvée sans jeton d'authentification est bloquée (401)."""
        client_externe = TestClient(app, client=("198.51.100.42", 5000))
        resp = client_externe.get("/jarvis/layout")
        self.assertEqual(resp.status_code, 401)

    def test_untrusted_ip_allowed_with_valid_bearer_token(self):
        """Une IP externe avec le jeton d'authentification valide est acceptée (200)."""
        client_externe = TestClient(app, client=("198.51.100.42", 5000))
        headers = {"Authorization": "Bearer super_secret_test_token_12345"}
        resp = client_externe.get("/jarvis/layout", headers=headers)
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
