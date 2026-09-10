import os
import unittest
from unittest.mock import MagicMock, patch

from core_intellect.llm_client import (
    BaseLLMProvider,
    GroqProvider,
    LLMClient,
    LLMConfig,
    LLMResponse,
    OllamaProvider,
    OpenRouterProvider,
    chat_with_cloud,
    chat_with_local,
    chat_with_openrouter,
    get_groq_clients,
    get_llm_client,
    memoriser_provider_cloud,
    ordonner_providers_cloud,
    providers_cloud_disponibles,
    register_event_emitter,
)

try:
    import pytest
except ImportError:
    class _MarkStub:
        def __getattr__(self, name):
            def _decorator(*args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:
                    return args[0]
                return lambda f: f
            return _decorator
    class _PytestStub:
        mark = _MarkStub()
    pytest = _PytestStub()  # type: ignore[assignment]


@pytest.mark.smoke
class LLMClientTests(unittest.TestCase):
    def setUp(self):
        self.client = LLMClient()

    def test_groq_provider_multi_keys(self):
        fake_env = {
            "GROQ_API_KEY_1": "key1",
            "GROQ_API_KEY_2": "key2",
        }
        with patch.dict(os.environ, fake_env, clear=True):
            with patch("core_intellect.llm_client.GroqClient") as mock_groq_cls:
                provider = GroqProvider()
                clients = provider.get_clients()
                self.assertEqual(len(clients), 2)
                self.assertEqual(mock_groq_cls.call_count, 2)

    def test_groq_provider_rotates_on_429(self):
        client1 = MagicMock()
        client1.chat.completions.create.side_effect = Exception("429 Rate limit exceeded")
        client2 = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Succès depuis clé 2"
        client2.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

        provider = GroqProvider()
        with patch.object(provider, "get_clients", return_value=[client1, client2]):
            resp = provider.generate("modele-test", [{"role": "user", "content": "hello"}])
            self.assertEqual(resp.content, "Succès depuis clé 2")
            self.assertEqual(resp.provider, "Groq")

    def test_openrouter_provider_generate(self):
        mock_response_data = b'{"choices": [{"message": {"content": "Reponse OpenRouter"}}]}'
        mock_cm = MagicMock()
        mock_cm.read.return_value = mock_response_data
        mock_cm.__enter__.return_value = mock_cm

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
            with patch("urllib.request.urlopen", return_value=mock_cm):
                provider = OpenRouterProvider()
                resp = provider.generate("model-or", [{"role": "system", "content": "sys"}, {"role": "user", "content": "msg"}])
                self.assertEqual(resp.content, "Reponse OpenRouter")
                self.assertEqual(resp.provider, "OpenRouter")

    def test_fallback_cascade_to_local_when_clouds_fail(self):
        fake_cloud = MagicMock(spec=BaseLLMProvider)
        fake_cloud.nom = "FakeCloud"
        fake_cloud.modeles = ["fake-model"]
        fake_cloud.niveau = "simple"
        fake_cloud.is_available.return_value = True
        fake_cloud.generate.side_effect = Exception("Cloud network down")

        fake_local = MagicMock(spec=BaseLLMProvider)
        fake_local.nom = "Ollama"
        fake_local.modeles = ["qwen2.5:7b"]
        fake_local.niveau = "local"
        fake_local.is_available.return_value = True
        fake_local.generate.return_value = LLMResponse(
            content="Reponse locale de secours",
            provider="Ollama",
            model="qwen2.5:7b",
        )

        fake_sovereign = MagicMock(spec=BaseLLMProvider)
        fake_sovereign.is_available.return_value = False

        client = LLMClient(
            cloud_providers=[fake_cloud],
            local_provider=fake_local,
            sovereign_provider=fake_sovereign,
        )

        events = []
        result = client.generate_with_fallback(
            messages=[{"role": "user", "content": "bonjour"}],
            on_event=lambda t, d: events.append((t, d)),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["message"]["content"], "Reponse locale de secours")
        self.assertEqual(events[-1], ("provider", {"provider": "Ollama", "model": "qwen2.5:7b"}))

    def test_compatibility_wrappers(self):
        self.assertIsNotNone(get_llm_client())
        with patch.object(GroqProvider, "is_available", return_value=True):
            providers = providers_cloud_disponibles()
            self.assertTrue(any(p["nom"] == "Groq" for p in providers))


if __name__ == "__main__":
    unittest.main()
