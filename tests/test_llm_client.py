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

    def test_default_local_model_is_3b(self):
        from core_intellect.llm_client import MODELE_LOCAL
        self.assertEqual(MODELE_LOCAL, "qwen2.5:3b")

    def test_groq_timeout_per_key(self):
        provider = GroqProvider()
        self.assertEqual(provider.timeout_per_key, 5.0)

    def test_openrouter_timeout_default_is_10s(self):
        provider = OpenRouterProvider()
        self.assertEqual(provider.default_timeout, 10.0)

    @patch("core_intellect.llm_client.ollama")
    def test_prechauffer_modele_local_invokes_ollama(self, mock_ollama):
        from core_intellect.llm_client import prechauffer_modele_local
        import time
        prechauffer_modele_local("qwen2.5:3b")
        time.sleep(0.1)
        mock_ollama.generate.assert_called_once_with(model="qwen2.5:3b", prompt="", keep_alive="5m")

    @patch("core_intellect.llm_client.prechauffer_modele_local")
    def test_prewarm_triggered_after_three_cloud_failures(self, mock_prewarm):
        cloud_p1 = MagicMock(spec=BaseLLMProvider)
        cloud_p1.nom = "Cloud1"
        cloud_p1.modeles = ["m1"]
        cloud_p1.niveau = "simple"
        cloud_p1.is_available.return_value = True

        def fail_with_two_keys(modele, msgs, config=None, on_key_failure=None, **kwargs):
            if on_key_failure:
                on_key_failure("Cloud1 Clé 1", Exception("err1"))
                on_key_failure("Cloud1 Clé 2", Exception("err2"))
            raise RuntimeError("Cloud1 out")
        cloud_p1.generate.side_effect = fail_with_two_keys

        cloud_p2 = MagicMock(spec=BaseLLMProvider)
        cloud_p2.nom = "Cloud2"
        cloud_p2.modeles = ["m2"]
        cloud_p2.niveau = "simple"
        cloud_p2.is_available.return_value = True

        def fail_on_third_key(modele, msgs, config=None, on_key_failure=None, **kwargs):
            if on_key_failure:
                on_key_failure("Cloud2 Clé 1", Exception("err3"))
            raise RuntimeError("Cloud2 out")
        cloud_p2.generate.side_effect = fail_on_third_key

        fake_local = MagicMock(spec=BaseLLMProvider)
        fake_local.nom = "Ollama"
        fake_local.modeles = ["qwen2.5:3b"]
        fake_local.niveau = "local"
        fake_local.is_available.return_value = True
        fake_local.generate.return_value = LLMResponse(content="OK", provider="Ollama", model="qwen2.5:3b")

        client = LLMClient(
            cloud_providers=[cloud_p1, cloud_p2],
            local_provider=fake_local,
            sovereign_provider=None,
        )

        res = client.generate_with_fallback([{"role": "user", "content": "test"}], max_tentatives=1)
        self.assertIsNotNone(res)
        mock_prewarm.assert_called_once_with("qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
