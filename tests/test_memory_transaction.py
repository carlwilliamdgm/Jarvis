import os
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datashield.crypto import CryptoEngine
from context_engine.memory_store import reset_memory_stores
from context_engine.memory import (
    charger_memoire,
    journaliser_action,
    transaction_memoire,
)


class MemoryTransactionTests(unittest.TestCase):
    def setUp(self):
        # Les tests ne doivent jamais sauvegarder, vider ou restaurer la mémoire
        # utilisateur du dépôt. Ils utilisent un fichier éphémère chiffré.
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        self._temporary_storage = tempfile.TemporaryDirectory(
            prefix="greatos-memory-test-", dir=temp_root,
        )
        self.addCleanup(self._temporary_storage.cleanup)

        self._backend_patch = patch.dict(os.environ, {"JARVIS_MEMORY_BACKEND": "encrypted"})
        self._path_patch = patch(
            "context_engine.memory_store.MEMORY_PATH",
            Path(self._temporary_storage.name) / "memory.json",
        )

        engine = CryptoEngine.__new__(CryptoEngine)
        engine._passphrase = b"isolated-test-key-not-for-production"
        engine._lock = threading.Lock()
        self._crypto_patch = patch("context_engine.encrypted_memory_store.crypto_engine", engine)

        self._backend_patch.start()
        self._path_patch.start()
        self._crypto_patch.start()
        reset_memory_stores()

        # unittest exécute les cleanup en ordre inverse : vider le singleton
        # avant de restaurer patches et de supprimer le répertoire temporaire.
        self.addCleanup(self._backend_patch.stop)
        self.addCleanup(self._path_patch.stop)
        self.addCleanup(self._crypto_patch.stop)
        self.addCleanup(reset_memory_stores)

    def test_transaction_commits_on_success(self):
        with transaction_memoire() as data:
            data["notes"].append("note de test transaction")

        reloaded = charger_memoire()
        self.assertIn("note de test transaction", reloaded.get("notes", []))

    def test_transaction_rolls_back_on_exception(self):
        try:
            with transaction_memoire() as data:
                data["notes"].append("cette note ne doit pas etre persistee")
                raise ValueError("Erreur métier inattendue")
        except ValueError:
            pass

        reloaded = charger_memoire()
        self.assertNotIn("cette note ne doit pas etre persistee", reloaded.get("notes", []))

    def test_concurrent_transactions_thread_safe(self):
        def worker(idx):
            for i in range(10):
                journaliser_action(f"outil_{idx}", {"step": i}, f"resultat_{idx}_{i}")

        # Ce test cible le verrouillage/atomicité, pas le coût du KDF. La suite
        # DataShield teste séparément AES-GCM avec le coût PBKDF2 de production.
        with patch("datashield.crypto.PBKDF2_ITERATIONS", 1):
            threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            data = charger_memoire()
            actions = data.get("historique_actions", [])
            self.assertEqual(len(actions), 50)


if __name__ == "__main__":
    unittest.main()
