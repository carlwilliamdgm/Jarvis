import os
import threading
import unittest
from pathlib import Path

from core.memory import (
    MEMORY_PATH,
    charger_memoire,
    journaliser_action,
    normaliser_memoire,
    sauvegarder_memoire,
    transaction_memoire,
)


class MemoryTransactionTests(unittest.TestCase):
    def setUp(self):
        self.backup = charger_memoire()
        sauvegarder_memoire({})

    def tearDown(self):
        sauvegarder_memoire(self.backup)

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
