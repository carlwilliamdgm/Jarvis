import unittest
from unittest.mock import MagicMock, patch
import os

from core_intellect.llm_client import (
    BaseLLMProvider,
    JarvisGCProvider,
    LLMClient,
    LLMConfig,
    LLMResponse,
    MODELE_SOUVERAIN_JARVIS,
    chat_with_jarvis_gc,
    modele_souverain_disponible,
)

class JarvisGCProviderTests(unittest.TestCase):
    def test_provider_initialization_defaults(self):
        provider = JarvisGCProvider()
        self.assertEqual(provider.nom, "Jarvis-GC")
        self.assertEqual(provider.niveau, "souverain")
        self.assertIn(MODELE_SOUVERAIN_JARVIS, provider.modeles)
        self.assertTrue(provider.host.startswith("http"))

    @patch("urllib.request.urlopen")
    def test_provider_is_available_when_endpoint_responds_200(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        provider = JarvisGCProvider()
        self.assertTrue(provider.is_available())

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_provider_is_not_available_when_endpoint_unreachable(self, mock_urlopen):
        provider = JarvisGCProvider()
        self.assertFalse(provider.is_available())

    @patch("core_intellect.llm_client.ollama")
    def test_provider_generate_nominal(self, mock_ollama):
        provider = JarvisGCProvider()
        
        # Mock is_available
        with patch.object(provider, "is_available", return_value=True):
            mock_client = MagicMock()
            mock_client.chat.return_value = {
                "message": {
                    "content": '{"objectif": "test", "type": "conversation", "actions": [], "reponse": "Bien reçu Sir."}'
                }
            }
            mock_ollama.Client.return_value = mock_client
            
            messages = [{"role": "user", "content": "Bonjour"}]
            cfg = LLMConfig(temperature=0.2)
            resp = provider.generate("jarvis-gc:latest", messages, config=cfg)
            
            self.assertEqual(resp.provider, "Jarvis-GC")
            self.assertEqual(resp.model, "jarvis-gc:latest")
            self.assertIn("Bien reçu Sir.", resp.content)
            
            # Vérification des arguments passés à chat (keep_alive)
            mock_client.chat.assert_called_once()
            call_kwargs = mock_client.chat.call_args[1]
            self.assertEqual(call_kwargs["keep_alive"], "5m")

    def test_cloud_first_sovereign_fallback_cascade(self):
        fake_sovereign = MagicMock(spec=JarvisGCProvider)
        fake_sovereign.nom = "Jarvis-GC"
        fake_sovereign.modeles = ["jarvis-gc:latest"]
        fake_sovereign.niveau = "souverain"
        fake_sovereign.is_available.return_value = True
        fake_sovereign.generate.return_value = LLMResponse(
            content='{"objectif": "check", "type": "conversation", "actions": [], "reponse": "Exécution souveraine."}',
            provider="Jarvis-GC",
            model="jarvis-gc:latest"
        )

        fake_cloud = MagicMock(spec=BaseLLMProvider)
        fake_cloud.nom = "Groq"
        fake_cloud.modeles = ["openai/gpt-oss-120b"]
        fake_cloud.niveau = "simple"
        fake_cloud.is_available.return_value = True
        fake_cloud.generate.return_value = LLMResponse(
            content='{"objectif": "check", "type": "conversation", "actions": [], "reponse": "Exécution cloud."}',
            provider="Groq",
            model="openai/gpt-oss-120b"
        )

        client = LLMClient(
            sovereign_provider=fake_sovereign,
            cloud_providers=[fake_cloud]
        )

        # 1. En présence de cloud, c'est le cloud (Groq) qui répond en priorité #1
        resp = client.generate_with_fallback([{"role": "user", "content": "test"}])
        self.assertEqual(resp["provider"], "Groq")
        fake_cloud.generate.assert_called_once()
        fake_sovereign.generate.assert_not_called()

        # 2. Si le cloud échoue, le fallback souverain prend le relais
        fake_cloud.generate.side_effect = RuntimeError("Cloud down")
        resp_fallback = client.generate_with_fallback([{"role": "user", "content": "test"}])
        self.assertEqual(resp_fallback["provider"], "Jarvis-GC")
        fake_sovereign.generate.assert_called_once()

    def test_jarvis_gc_timeout_triggers_timeout_error(self):
        provider = JarvisGCProvider(timeout=0.05)
        with patch.object(provider, "is_available", return_value=True):
            with patch("core_intellect.llm_client.ollama") as mock_ollama:
                mock_client = MagicMock()
                import time
                def slow_chat(**kwargs):
                    time.sleep(0.3)
                    return {"message": {"content": "ok"}}
                mock_client.chat.side_effect = slow_chat
                mock_ollama.Client.return_value = mock_client

                with self.assertRaises(TimeoutError):
                    provider.generate("jarvis-gc:latest", [{"role": "user", "content": "hi"}], config=LLMConfig(timeout=0.05))

    def test_sticky_last_valid_cloud_provider(self):
        p_groq = MagicMock(spec=BaseLLMProvider)
        p_groq.nom = "Groq"
        p_groq.niveau = "simple"

        p_openrouter = MagicMock(spec=BaseLLMProvider)
        p_openrouter.nom = "OpenRouter"
        p_openrouter.niveau = "simple"

        client = LLMClient()
        memoire = {
            "routeur_modeles": {
                "dernier_provider_simple": "OpenRouter",
                "dernier_provider_cloud": "OpenRouter"
            }
        }

        ordered = client.order_cloud_providers([p_groq, p_openrouter], memoire=memoire, complexite="simple")
        # OpenRouter (le dernier valide) doit être placé en premier
        self.assertEqual(ordered[0].nom, "OpenRouter")
        self.assertEqual(ordered[1].nom, "Groq")


if __name__ == "__main__":
    unittest.main()
